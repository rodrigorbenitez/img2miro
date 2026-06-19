"""Vision extraction: diagram image -> Diagram via the Anthropic API.

Uses claude-opus-4-8 with streaming, adaptive thinking, and structured
outputs (json_schema) so the response is guaranteed to parse against the
Diagram schema.
"""

import base64
import sys
from pathlib import Path

import anthropic

from .schema import Diagram

# Models that support this call shape (adaptive thinking + structured
# outputs + vision). Haiku is excluded: it doesn't support adaptive thinking.
SUPPORTED_MODELS = ["claude-opus-4-8", "claude-fable-5", "claude-sonnet-4-6"]
DEFAULT_MODEL = "claude-opus-4-8"

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


def _source_block(image_path: Path) -> dict:
    suffix = image_path.suffix.lower()
    if suffix == ".svg":
        svg = image_path.read_text(encoding="utf-8")
        if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
            raise ValueError(
                f"SVG file is too large ({image_path.stat().st_size} bytes; "
                f"limit {MAX_SVG_BYTES}). Likely it embeds raster images — "
                "export the diagram as PNG instead."
            )
        return {"type": "text", "text": SVG_PREAMBLE.format(svg=svg)}

    media_type = MEDIA_TYPES.get(suffix)
    if media_type is None:
        supported = ", ".join(sorted([*MEDIA_TYPES, ".svg"]))
        raise ValueError(
            f"Unsupported image type '{image_path.suffix}'. Supported: {supported}"
        )
    data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _call(client: anthropic.Anthropic, content: list[dict], model: str) -> Diagram:
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={
            "format": {
                "type": "json_schema",
                "schema": Diagram.model_json_schema(),
            }
        },
        messages=[{"role": "user", "content": content}],
    ) as stream:
        for _ in stream.text_stream:
            print(".", end="", flush=True)
        message = stream.get_final_message()
    print(flush=True)
    if message.stop_reason == "refusal":
        raise RuntimeError(
            "The model declined to process this image (stop_reason=refusal). "
            "Try a different image."
        )
    text = next(b.text for b in message.content if b.type == "text")
    return Diagram.model_validate_json(text)


def extract(
    client: anthropic.Anthropic,
    image_path: Path,
    refine: bool = True,
    model: str = DEFAULT_MODEL,
) -> Diagram:
    image = _source_block(image_path)

    print(f"Extracting diagram ({model})", end="", flush=True, file=sys.stderr)
    diagram = _call(client, [image, {"type": "text", "text": EXTRACT_PROMPT}], model)

    if refine:
        print("Refining extraction", end="", flush=True, file=sys.stderr)
        prompt = REFINE_PROMPT.format(json=diagram.model_dump_json(indent=2))
        diagram = _call(client, [image, {"type": "text", "text": prompt}], model)

    return diagram
