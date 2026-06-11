"""Pydantic v2 models describing an extracted diagram.

`extra="forbid"` makes pydantic emit `additionalProperties: false` in the
JSON schema, which the Anthropic structured-outputs API requires on every
object. All fields are required so the model must emit complete items.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShapeType = Literal[
    "rectangle",
    "round_rectangle",
    "circle",
    "triangle",
    "rhombus",
    "parallelogram",
    "trapezoid",
    "pentagon",
    "hexagon",
    "octagon",
    "star",
    "cloud",
    "can",
    "right_arrow",
    "left_arrow",
]

ConnectorStyle = Literal["straight", "elbowed", "curved"]
FontCategory = Literal["sans", "serif", "handwritten"]
TextAlign = Literal["left", "center", "right"]
TextValign = Literal["top", "middle", "bottom"]
LineStyle = Literal["normal", "dashed", "dotted"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(StrictModel):
    id: str = Field(description="Unique identifier for this node, e.g. 'n1'")
    shape: ShapeType = Field(description="Closest matching Miro shape type")
    text: str = Field(
        description=(
            "Text inside the shape, copied VERBATIM (exact characters, casing, "
            "punctuation). Preserve line breaks as '\\n'. Empty string if none."
        )
    )
    x: float = Field(description="Center x in pixels, relative to the image")
    y: float = Field(description="Center y in pixels, relative to the image")
    width: float = Field(description="Width in pixels")
    height: float = Field(description="Height in pixels")
    fill_color: str = Field(description="Exact hex fill color, e.g. '#ffffff'")
    border_color: str = Field(description="Exact hex border color, e.g. '#1a1a1a'")
    border_width: float = Field(description="Border thickness in pixels")
    border_style: LineStyle = Field(
        description="'dashed' or 'dotted' if drawn that way, otherwise 'normal'"
    )
    text_color: str = Field(description="Exact hex text color, e.g. '#1a1a1a'")
    font_size: float = Field(description="Font size in image pixels")
    font: FontCategory = Field(
        description="'serif' if letters have serifs, 'handwritten' for script-like text, else 'sans'"
    )
    text_align: TextAlign = Field(
        description="Horizontal alignment of the text inside the shape"
    )
    text_valign: TextValign = Field(
        description=(
            "Vertical placement of the text inside the shape. Use 'top' for "
            "container/group titles that sit at the top edge of a large box."
        )
    )


class TextLabel(StrictModel):
    """Standalone text not enclosed by a shape: icon captions, titles,
    annotations, legend entries. Rendered as a Miro text item at its exact
    position so the layout mirrors the image."""

    text: str = Field(
        description="The text, copied VERBATIM. Preserve line breaks as '\\n'."
    )
    x: float = Field(description="Center x of the text block in image pixels")
    y: float = Field(description="Center y of the text block in image pixels")
    width: float = Field(description="Width of the text block in pixels")
    font_size: float = Field(description="Font size in image pixels")
    font: FontCategory = Field(
        description="'serif' if letters have serifs, 'handwritten' for script-like text, else 'sans'"
    )
    color: str = Field(description="Exact hex text color, e.g. '#1a1a1a'")
    text_align: TextAlign = Field(description="Horizontal alignment of the text")


class Connector(StrictModel):
    from_id: str = Field(description="id of the source node")
    to_id: str = Field(description="id of the target node")
    label: str = Field(description="Label on the connector; empty string if none")
    style: ConnectorStyle = Field(description="Line routing style")
    stroke_color: str = Field(description="Exact hex color of the line, e.g. '#555555'")
    stroke_style: LineStyle = Field(
        description="'dashed' or 'dotted' if drawn that way, otherwise 'normal'"
    )


class Diagram(StrictModel):
    nodes: list[Node]
    labels: list[TextLabel]
    connectors: list[Connector]
