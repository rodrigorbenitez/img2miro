"""Local SVG preview of an extracted Diagram, written to a temp file."""

import html
import tempfile
from pathlib import Path

from .schema import Diagram, Node

PADDING = 40


def _node_svg(node: Node) -> str:
    x0, y0 = node.x - node.width / 2, node.y - node.height / 2
    style = (
        f'fill="{node.fill_color}" stroke="{node.border_color}" stroke-width="2"'
    )
    if node.shape == "circle":
        element = (
            f'<ellipse cx="{node.x}" cy="{node.y}" rx="{node.width / 2}" '
            f'ry="{node.height / 2}" {style}/>'
        )
    elif node.shape == "rhombus":
        points = (
            f"{node.x},{y0} {x0 + node.width},{node.y} "
            f"{node.x},{y0 + node.height} {x0},{node.y}"
        )
        element = f'<polygon points="{points}" {style}/>'
    elif node.shape == "triangle":
        points = f"{node.x},{y0} {x0 + node.width},{y0 + node.height} {x0},{y0 + node.height}"
        element = f'<polygon points="{points}" {style}/>'
    else:
        rx = ' rx="8"' if node.shape == "round_rectangle" else ""
        element = (
            f'<rect x="{x0}" y="{y0}" width="{node.width}" '
            f'height="{node.height}"{rx} {style}/>'
        )
    label = (
        f'<text x="{node.x}" y="{node.y}" text-anchor="middle" '
        f'dominant-baseline="middle" fill="{node.text_color}" '
        f'font-family="sans-serif" font-size="13">{html.escape(node.text)}</text>'
    )
    return element + label


def render_svg(diagram: Diagram) -> str:
    if diagram.nodes:
        max_x = max(n.x + n.width / 2 for n in diagram.nodes) + PADDING
        max_y = max(n.y + n.height / 2 for n in diagram.nodes) + PADDING
    else:
        max_x = max_y = 2 * PADDING

    centers = {n.id: (n.x, n.y) for n in diagram.nodes}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{max_x}" height="{max_y}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="7" refX="9" '
        'refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" '
        'fill="#555"/></marker></defs>',
        f'<rect width="{max_x}" height="{max_y}" fill="#fafafa"/>',
    ]

    for c in diagram.connectors:
        if c.from_id not in centers or c.to_id not in centers:
            continue
        (x1, y1), (x2, y2) = centers[c.from_id], centers[c.to_id]
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#555" '
            'stroke-width="1.5" marker-end="url(#arrow)"/>'
        )
        if c.label:
            parts.append(
                f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 5}" '
                'text-anchor="middle" fill="#555" font-family="sans-serif" '
                f'font-size="11">{html.escape(c.label)}</text>'
            )

    parts.extend(_node_svg(n) for n in diagram.nodes)
    parts.append("</svg>")
    return "\n".join(parts)


def write_preview(diagram: Diagram) -> Path:
    svg = render_svg(diagram)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".svg", prefix="img2miro_", delete=False, encoding="utf-8"
    ) as f:
        f.write(svg)
        return Path(f.name)
