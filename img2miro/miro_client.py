"""Miro REST API v2 client and the pure mapping layer (Diagram -> payloads).

The payload builders and push_diagram are pure with respect to the network:
push_diagram takes any object with create_shape/create_connector methods, so
tests run against a fake client.
"""

import html
import math
from urllib.parse import quote

import requests

from .schema import Connector, Diagram, Node, TextLabel

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

# Rough text metrics used to keep text inside its shape. Deliberately
# conservative — Miro renders wider than the geometric average, and an
# overestimate only costs a slightly smaller font while an underestimate
# hides text behind the shape edge.
TEXT_PADDING = 10.0
LINE_HEIGHT = 1.4
CHAR_WIDTH = 0.62  # average glyph width as a fraction of font size


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def wrapped_line_count(text: str, font_size: float, avail_w: float) -> int:
    lines = 0
    for line in text.split("\n"):
        line_px = max(len(line), 1) * CHAR_WIDTH * font_size
        lines += max(1, math.ceil(line_px / avail_w))
    return lines


def _text_fits(text: str, font_size: float, avail_w: float, avail_h: float) -> bool:
    lines = wrapped_line_count(text, font_size, avail_w)
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


def text_payload(label: TextLabel) -> dict:
    return {
        "data": {"content": content_html(label.text)},
        "style": {
            "color": label.color,
            "fontFamily": FONT_FAMILIES[label.font],
            "fontSize": str(int(_clamp(label.font_size, MIN_FONT_SIZE, MAX_FONT_SIZE))),
            "textAlign": label.text_align,
        },
        "position": {"x": label.x, "y": label.y},
        "geometry": {"width": max(label.width, 10.0)},
    }


def _relative_position(px: float, py: float, node: Node) -> dict:
    """Image-pixel attachment point -> Miro percentage position on the item."""
    rx = (px - (node.x - node.width / 2)) / node.width
    ry = (py - (node.y - node.height / 2)) / node.height
    return {
        "x": f"{_clamp(rx, 0.0, 1.0) * 100:.1f}%",
        "y": f"{_clamp(ry, 0.0, 1.0) * 100:.1f}%",
    }


def connector_payload(
    connector: Connector, id_map: dict[str, str], nodes: dict[str, Node]
) -> dict:
    # Pin both endpoints to the exact spots where the line touches each
    # shape in the image. Without this, Miro auto-snaps and parallel arrows
    # (e.g. forward + feedback between the same two blocks) collapse onto
    # the same path.
    payload = {
        "startItem": {
            "id": id_map[connector.from_id],
            "position": _relative_position(
                connector.from_x, connector.from_y, nodes[connector.from_id]
            ),
        },
        "endItem": {
            "id": id_map[connector.to_id],
            "position": _relative_position(
                connector.to_x, connector.to_y, nodes[connector.to_id]
            ),
        },
        "shape": connector.style,
        "style": {
            "strokeColor": connector.stroke_color,
            "strokeStyle": connector.stroke_style,
            "startStrokeCap": "stealth" if connector.start_arrow else "none",
            "endStrokeCap": "stealth" if connector.end_arrow else "none",
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
    # containers sit behind the nodes drawn inside them, and text labels
    # last so they sit on top of everything.
    id_map: dict[str, str] = {}
    for node in sorted(diagram.nodes, key=lambda n: n.width * n.height, reverse=True):
        id_map[node.id] = client.create_shape(shape_payload(node))

    for label in diagram.labels:
        client.create_text(text_payload(label))

    nodes_by_id = {node.id: node for node in diagram.nodes}
    created = 0
    skipped: list[Connector] = []
    for connector in diagram.connectors:
        if connector.from_id in id_map and connector.to_id in id_map:
            client.create_connector(connector_payload(connector, id_map, nodes_by_id))
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

    def create_text(self, payload: dict) -> str:
        return self._post("texts", payload)

    def create_connector(self, payload: dict) -> str:
        return self._post("connectors", payload)

    @property
    def board_url(self) -> str:
        return f"https://miro.com/app/board/{self.board_id}/"
