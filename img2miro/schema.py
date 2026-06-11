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


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(StrictModel):
    id: str = Field(description="Unique identifier for this node, e.g. 'n1'")
    shape: ShapeType = Field(description="Closest matching Miro shape type")
    text: str = Field(description="Text inside the shape; empty string if none")
    x: float = Field(description="Center x in pixels, relative to the image")
    y: float = Field(description="Center y in pixels, relative to the image")
    width: float = Field(description="Width in pixels")
    height: float = Field(description="Height in pixels")
    fill_color: str = Field(description="Hex fill color, e.g. '#ffffff'")
    border_color: str = Field(description="Hex border color, e.g. '#1a1a1a'")
    text_color: str = Field(description="Hex text color, e.g. '#1a1a1a'")


class Connector(StrictModel):
    from_id: str = Field(description="id of the source node")
    to_id: str = Field(description="id of the target node")
    label: str = Field(description="Label on the connector; empty string if none")
    style: ConnectorStyle = Field(description="Line routing style")


class Diagram(StrictModel):
    nodes: list[Node]
    connectors: list[Connector]
