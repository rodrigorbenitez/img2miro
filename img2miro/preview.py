"""Local SVG preview of an extracted Diagram, written to a temp file."""

import html
import tempfile
from pathlib import Path

from .schema import Diagram, Node

PADDING = 40

FONT_STACKS = {
    "sans": "sans-serif",
    "serif": "serif",
    "handwritten": "cursive",
}

DASH_ARRAYS = {
    "normal": "",
    "dashed": ' stroke-dasharray="8,4"',
    "dotted": ' stroke-dasharray="2,3"',
}


def _node_svg(node: Node) -> str:
    x0, y0 = node.x - node.width / 2, node.y - node.height / 2
    style = (
        f'fill="{node.fill_color}" stroke="{node.border_color}" '
        f'stroke-width="{node.border_width}"{DASH_ARRAYS[node.border_style]}'
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
    return element + _text_svg(node, x0)


def _text_svg(node: Node, x0: float) -> str:
    if not node.text:
        return ""
    if node.text_align == "left":
        anchor, text_x = "start", x0 + 8
    elif node.text_align == "right":
        anchor, text_x = "end", x0 + node.width - 8
    else:
        anchor, text_x = "middle", node.x

    lines = node.text.split("\n")
    line_height = node.font_size * 1.25
    start_y = node.y - line_height * (len(lines) - 1) / 2
    spans = "".join(
        f'<tspan x="{text_x}" y="{start_y + i * line_height}">{html.escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<text text-anchor="{anchor}" dominant-baseline="middle" '
        f'fill="{node.text_color}" font-family="{FONT_STACKS[node.font]}" '
        f'font-size="{node.font_size}">{spans}</text>'
    )


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
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{c.stroke_color}" stroke-width="1.5"'
            f'{DASH_ARRAYS[c.stroke_style]} marker-end="url(#arrow)"/>'
        )
        if c.label:
            parts.append(
                f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 5}" '
                f'text-anchor="middle" fill="{c.stroke_color}" '
                'font-family="sans-serif" font-size="11">'
                f"{html.escape(c.label)}</text>"
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
