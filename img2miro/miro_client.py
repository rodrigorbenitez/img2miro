"""Miro REST API v2 client and the pure mapping layer (Diagram -> payloads).

The payload builders and push_diagram are pure with respect to the network:
push_diagram takes any object with create_shape/create_connector methods, so
tests run against a fake client.
"""

import html
import math
from urllib.parse import quote

import requests

from .schema import Connector, Diagram, Node

API_BASE = "https://api.miro.com/v2"

# Map extracted font categories onto known-valid Miro fontFamily values.
FONT_FAMILIES = {
    "sans": "open_sans",
    "serif": "pt_serif",
    "handwritten": "caveat",
}

# Miro-accepted ranges; values outside them are rejected with a 400.
MIN_FONT_SIZE, MAX_FONT_SIZE = 10, 288
MIN_BORDER_WIDTH, MAX_BORDER_WIDTH = 1.0, 24.0

# Rough text metrics used to keep text inside its shape.
TEXT_PADDING = 10.0
LINE_HEIGHT = 1.3
CHAR_WIDTH = 0.55  # average glyph width as a fraction of font size


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _text_fits(text: str, font_size: float, avail_w: float, avail_h: float) -> bool:
    lines = 0
    for line in text.split("\n"):
        line_px = max(len(line), 1) * CHAR_WIDTH * font_size
        lines += max(1, math.ceil(line_px / avail_w))
    return lines * font_size * LINE_HEIGHT <= avail_h


def fitted_font_size(node: Node) -> int:
    """Largest font size <= the extracted one whose wrapped text fits the shape."""
    size = int(_clamp(node.font_size, MIN_FONT_SIZE, MAX_FONT_SIZE))
    if not node.text:
        return size
    avail_w = max(node.width - 2 * TEXT_PADDING, 20.0)
    avail_h = max(node.height - 2 * TEXT_PADDING, 12.0)
    while size > MIN_FONT_SIZE and not _text_fits(node.text, size, avail_w, avail_h):
        size -= 1
    return size


def content_html(text: str) -> str:
    """Verbatim text -> Miro rich-text content, preserving line breaks."""
    if not text:
        return ""
    lines = [html.escape(line) for line in text.split("\n")]
    return "<p>" + "<br>".join(lines) + "</p>"


def shape_payload(node: Node) -> dict:
    return {
        "data": {"shape": node.shape, "content": content_html(node.text)},
        "style": {
            "fillColor": node.fill_color,
            "borderColor": node.border_color,
            "borderWidth": str(round(_clamp(node.border_width, MIN_BORDER_WIDTH, MAX_BORDER_WIDTH), 1)),
            "borderStyle": node.border_style,
            "color": node.text_color,
            "fontFamily": FONT_FAMILIES[node.font],
            "fontSize": str(fitted_font_size(node)),
            "textAlign": node.text_align,
            "textAlignVertical": node.text_valign,
            # Without these (as strings), Miro creates the shapes invisible.
            "fillOpacity": "1.0",
            "borderOpacity": "1.0",
        },
        "position": {"x": node.x, "y": node.y},
        "geometry": {"width": node.width, "height": node.height},
    }


def connector_payload(connector: Connector, id_map: dict[str, str]) -> dict:
    payload = {
        "startItem": {"id": id_map[connector.from_id]},
        "endItem": {"id": id_map[connector.to_id]},
        "shape": connector.style,
        "style": {
            "strokeColor": connector.stroke_color,
            "strokeStyle": connector.stroke_style,
        },
    }
    if connector.label:
        payload["captions"] = [{"content": html.escape(connector.label)}]
    return payload


def push_diagram(client, diagram: Diagram) -> tuple[dict[str, str], int, list[Connector]]:
    """Create all items on the board.

    Returns (node id -> Miro item id, connectors created, connectors skipped
    because an endpoint id didn't resolve to a created node).
    """
    # Miro z-order follows creation order: create largest shapes first so
    # containers sit behind the nodes drawn inside them.
    id_map: dict[str, str] = {}
    for node in sorted(diagram.nodes, key=lambda n: n.width * n.height, reverse=True):
        id_map[node.id] = client.create_shape(shape_payload(node))

    created = 0
    skipped: list[Connector] = []
    for connector in diagram.connectors:
        if connector.from_id in id_map and connector.to_id in id_map:
            client.create_connector(connector_payload(connector, id_map))
            created += 1
        else:
            skipped.append(connector)
    return id_map, created, skipped


class MiroClient:
    def __init__(self, token: str, board_id: str):
        self.board_id = board_id
        self.base = f"{API_BASE}/boards/{quote(board_id, safe='')}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _post(self, path: str, payload: dict) -> str:
        response = self.session.post(f"{self.base}/{path}", json=payload)
        response.raise_for_status()
        return response.json()["id"]

    def create_shape(self, payload: dict) -> str:
        return self._post("shapes", payload)

    def create_connector(self, payload: dict) -> str:
        return self._post("connectors", payload)

    @property
    def board_url(self) -> str:
        return f"https://miro.com/app/board/{self.board_id}/"
