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

MODEL = "claude-opus-4-8"

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

EXTRACT_PROMPT = """\
Extract every element of this diagram so it can be rebuilt as editable items \
on a whiteboard.

- One node per visual shape or box. Use pixel coordinates from the image for \
position (center) and size.
- Pick the closest available shape type; plain boxes are 'rectangle' or \
'round_rectangle'.
- Capture text verbatim, including line breaks as spaces.
- Sample the actual colors as hex values. If a shape has no visible fill, use \
'#ffffff'.
- One connector per arrow or line between shapes, with its label if any.
"""

REFINE_PROMPT = """\
Below is a JSON extraction of this diagram. Compare it carefully against the \
image and return a corrected version of the full JSON: fix missing or \
hallucinated nodes, wrong text, wrong colors, misplaced or misdirected \
connectors, and positions that don't match the layout. Return the complete \
corrected diagram, not a diff.

Current extraction:
{json}
"""


def _image_block(image_path: Path) -> dict:
    media_type = MEDIA_TYPES.get(image_path.suffix.lower())
    if media_type is None:
        raise ValueError(
            f"Unsupported image type '{image_path.suffix}'. "
            f"Supported: {', '.join(sorted(MEDIA_TYPES))}"
        )
    data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _call(client: anthropic.Anthropic, content: list[dict]) -> Diagram:
    with client.messages.stream(
        model=MODEL,
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
    text = next(b.text for b in message.content if b.type == "text")
    return Diagram.model_validate_json(text)


def extract(client: anthropic.Anthropic, image_path: Path, refine: bool = True) -> Diagram:
    image = _image_block(image_path)

    print("Extracting diagram", end="", flush=True, file=sys.stderr)
    diagram = _call(client, [image, {"type": "text", "text": EXTRACT_PROMPT}])

    if refine:
        print("Refining extraction", end="", flush=True, file=sys.stderr)
        prompt = REFINE_PROMPT.format(json=diagram.model_dump_json(indent=2))
        diagram = _call(client, [image, {"type": "text", "text": prompt}])

    return diagram
