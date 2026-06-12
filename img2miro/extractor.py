"""Vision extraction: diagram image -> Diagram via the Claude Agent SDK.

Runs the extraction through the Claude Code CLI (claude-agent-sdk), so usage
bills the user's Claude subscription (``claude /login`` or
CLAUDE_CODE_OAUTH_TOKEN) instead of an Anthropic API key. The agent gets a
single tool — Read, to view the image — and its output is constrained to JSON
matching the Diagram schema, which we parse and validate locally with pydantic.
"""

import asyncio
import json
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLINotFoundError,
    ResultMessage,
    query,
)
from pydantic import ValidationError

from .schema import Diagram

# Models worth using for this task (most capable first). Haiku is excluded:
# extraction fidelity drops too far below the smaller models.
SUPPORTED_MODELS = ["claude-fable-5", "claude-opus-4-8", "claude-sonnet-4-6"]
DEFAULT_MODEL = "claude-fable-5"

# Raster formats the agent can view with the Read tool.
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# SVGs are sent as source text, not pixels — the markup carries exact
# coordinates, colors, fonts, and text, so nothing has to be estimated.
MAX_SVG_BYTES = 800_000

SVG_PREAMBLE = """\
The diagram is provided as SVG source code below (not as a rendered image). \
Read positions, sizes, colors, fonts, and text EXACTLY from the markup — do \
not estimate anything that is stated literally. Treat SVG user units as \
pixels. Account for transform/translate attributes when computing absolute \
positions. Everything else in the instructions that says 'image' applies to \
the rendered result of this SVG.

```svg
{svg}
```

"""

IMAGE_PREAMBLE = """\
First use the Read tool to view the diagram image at this exact path:
{path}

Then follow the instructions below, working from what you see in that image.

"""

JSON_INSTRUCTION = """\


Return the extracted diagram as a single JSON object matching the required \
schema. Output ONLY the JSON — no markdown fences, no commentary.\
"""

EXTRACT_PROMPT = """\
Extract every element of this diagram so it can be rebuilt as a near-perfect \
copy on a whiteboard. The rebuilt diagram must look like a mirror of the \
original: same text, same colors, same sizes, same styles. Fidelity matters \
more than anything else.

- One node per visual shape or box. Use pixel coordinates from the image for \
position (center) and size.
- Pick the closest available shape type; plain boxes are 'rectangle' or \
'round_rectangle'.
- text: copy VERBATIM, character by character — exact casing, punctuation, \
accents, numbers. Preserve line breaks as '\\n'. Never paraphrase, translate, \
abbreviate, or fix typos.
- font_size: the text height in image pixels (uppercase letter height is \
roughly 70% of the font size).
- text_align: how the text is aligned inside the shape (left/center/right).
- font: 'serif' if the letters have serifs, 'handwritten' for script-like \
text, otherwise 'sans'.
- Colors: sample the actual pixels and report exact hex values — fill, \
border, and text color independently (they often differ). Use '#ffffff' for \
shapes with no visible fill.
- border_width: the border thickness in pixels. border_style: 'dashed' or \
'dotted' only if drawn that way.
- One connector PER DRAWN LINE. If two shapes are joined by two separate \
arrows (e.g. a forward arrow and a feedback arrow), emit TWO connectors — \
NEVER merge them into one. A single line with arrowheads on both ends is \
ONE connector with start_arrow and end_arrow both true.
- from_x/from_y and to_x/to_y: the exact pixel coordinates where the line \
visibly touches the source shape and the target shape. 'from' is the tail \
of the arrow, 'to' is the head — direction matters.
- start_arrow / end_arrow: whether an arrowhead is drawn at each end of \
the line.
- Each connector also carries its label, exact stroke color, and dash \
style, and must join the two shapes the original line visually joins — \
never an unrelated or distant shape.

Complex diagrams — follow these rules strictly:
- Containers and groups (large boxes that enclose other shapes, swimlanes, \
zones) are nodes too. Give them their full bounds, their title as text, and \
text_valign 'top' so the title sits at the top edge like in the image.
- Every child shape must lie COMPLETELY inside its container's bounds: \
child.x ± child.width/2 and child.y ± child.height/2 must stay within the \
container's rectangle. Check the arithmetic.
- Labels must be complete. Never cut text off mid-word or mid-sentence; if \
text is long, capture all of it and size the shape generously enough to \
hold it.
- font_size must be small enough that the text plausibly fits inside the \
shape's width and height.
- If shapes appear aligned in a row or column in the image, give them \
exactly the same y (row) or x (column) so the result is cleanly aligned.
- Icons and logos (cloud services, products, etc.) cannot be reproduced. \
Emit each one as a plain 'rectangle' node with EMPTY text (''), at the \
icon's exact position and size, filled with the icon's dominant color. \
NEVER put the icon's caption or name inside this square.
- Any text printed near an icon (its name below, above, or beside it), and \
any standalone text not enclosed by a shape (titles, annotations, legend \
entries), goes in 'labels' — each at its exact pixel position with its own \
size, color, font, and alignment. If a caption sits below an icon in the \
image, the label's y must place it below the icon's square, exactly \
mirroring the image.
- Do not emit empty decorative shapes or unused containers unless they \
genuinely appear in the image (icon placeholder squares are the exception).
"""

REFINE_PROMPT = """\
Below is a JSON extraction of this diagram. The goal is a near-perfect \
mirror of the image. Audit it field by field against the image and return a \
corrected version of the full JSON:

- Text: compare character by character. Fix any paraphrasing, wrong casing, \
missing punctuation, or lost line breaks ('\\n').
- Colors: re-sample fill, border, and text colors of every node and the \
stroke color of every connector; correct any that are off.
- Sizes and styles: check font_size, text_align, font category, \
border_width, and border_style against what is actually drawn.
- Structure: fix missing or hallucinated nodes, misplaced positions, and \
misdirected or missing connectors.
- Completeness: no label may end mid-word or mid-sentence; re-read the \
image and complete any truncated text.
- Containment: every child shape must lie fully inside its container's \
bounds — verify the arithmetic and move or resize offenders.
- Fit: font_size must be small enough for the text to fit the shape; \
enlarge the shape or reduce font_size where text would overflow.
- Alignment: shapes that form a row or column in the image must share \
exactly the same y or x.
- Icons: each icon/logo must be an empty square node, with its caption as a \
separate entry in 'labels' positioned exactly as in the image (e.g. below \
the icon) — never as text inside the square.
- Labels: verify each label's position, width, font size, color, and \
alignment against the image; add any standalone text that was missed.
- Connectors: there must be exactly as many connectors as drawn lines — \
re-count them in the image. Verify each one's endpoint coordinates \
(from_x/from_y, to_x/to_y) against where the line actually touches the \
shapes, its direction (tail vs arrowhead), and its arrowheads \
(start_arrow/end_arrow). Two arrows between the same two shapes must stay \
two separate connectors with their own distinct endpoints.
- Remove orphaned or placeholder shapes that don't exist in the image \
(icon placeholder squares are expected and stay).

Return the complete corrected diagram, not a diff.

Current extraction:
{json}
"""


def _source_part(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix == ".svg":
        svg = image_path.read_text(encoding="utf-8")
        if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
            raise ValueError(
                f"SVG file is too large ({image_path.stat().st_size} bytes; "
                f"limit {MAX_SVG_BYTES}). Likely it embeds raster images — "
                "export the diagram as PNG instead."
            )
        return SVG_PREAMBLE.format(svg=svg)

    if suffix not in MEDIA_TYPES:
        supported = ", ".join(sorted([*MEDIA_TYPES, ".svg"]))
        raise ValueError(
            f"Unsupported image type '{image_path.suffix}'. Supported: {supported}"
        )
    return IMAGE_PREAMBLE.format(path=image_path.resolve())


def _validate_diagram(data: object) -> Diagram:
    try:
        return Diagram.model_validate(data)
    except ValidationError as exc:
        raise RuntimeError(
            f"The model's JSON does not match the diagram schema:\n{exc}"
        ) from exc


def _parse_diagram(text: str) -> Diagram:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        snippet = text.strip()[:200]
        raise RuntimeError(
            f"The model did not return valid JSON ({exc}). "
            f"Response began with: {snippet!r}"
        ) from exc
    return _validate_diagram(data)


def _agent_output(prompt: str, model: str, cwd: Path) -> str | dict:
    """Run one non-interactive agent turn; return the structured output
    (dict) if the CLI produced one, otherwise the final response text."""
    options = ClaudeAgentOptions(
        model=model,
        tools=["Read"],  # the agent's entire tool set: just viewing the image
        allowed_tools=["Read"],  # ...and it runs without permission prompts
        max_turns=8,
        cwd=cwd,
        output_format={"type": "json_schema", "schema": Diagram.model_json_schema()},
    )

    async def _run() -> ResultMessage | None:
        result = None
        async for message in query(prompt=prompt, options=options):
            print(".", end="", flush=True, file=sys.stderr)
            if isinstance(message, ResultMessage):
                result = message
        return result

    try:
        result = asyncio.run(_run())
    except CLINotFoundError as exc:
        raise RuntimeError(
            "Claude Code CLI not found. Install it with "
            "`npm install -g @anthropic-ai/claude-code`, then sign in with "
            "your Claude account via `claude auth login` (requires a Claude "
            "Pro/Max subscription)."
        ) from exc
    except ClaudeSDKError as exc:
        raise RuntimeError(f"Claude Code agent failed: {exc}") from exc
    finally:
        print(flush=True, file=sys.stderr)

    if result is None:
        raise RuntimeError("The agent finished without producing a result.")
    if result.is_error:
        details = "; ".join(result.errors or []) or result.result or ""
        raise RuntimeError(
            f"Extraction failed ({result.subtype})"
            + (f": {details}" if details else ".")
        )
    if result.structured_output is not None:
        return result.structured_output
    if not result.result:
        raise RuntimeError(
            "The model returned an empty response. "
            "Try again or use a different image."
        )
    return result.result


def _call(prompt: str, model: str, cwd: Path) -> Diagram:
    output = _agent_output(prompt, model, cwd)
    if isinstance(output, str):
        return _parse_diagram(output)
    return _validate_diagram(output)


def extract(
    image_path: Path,
    refine: bool = True,
    model: str = DEFAULT_MODEL,
) -> Diagram:
    source = _source_part(image_path)
    cwd = image_path.resolve().parent

    print(f"Extracting diagram ({model})", end="", flush=True, file=sys.stderr)
    diagram = _call(source + EXTRACT_PROMPT + JSON_INSTRUCTION, model, cwd)

    if refine:
        print("Refining extraction", end="", flush=True, file=sys.stderr)
        prompt = REFINE_PROMPT.format(json=diagram.model_dump_json(indent=2))
        diagram = _call(source + prompt + JSON_INSTRUCTION, model, cwd)

    return diagram
