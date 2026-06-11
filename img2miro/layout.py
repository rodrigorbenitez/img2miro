"""Post-extraction layout normalization.

The vision model gets geometry approximately right; these passes enforce the
two invariants Miro cannot fix on its own:

1. Text must fit its shape — if even the minimum font size overflows, the
   shape grows taller (overflowing text is clipped/hidden by Miro).
2. Shapes that are visually nested (mostly overlapping a larger shape) must
   lie fully inside that container, below its title strip.
"""

from .miro_client import (
    LINE_HEIGHT,
    TEXT_PADDING,
    fitted_font_size,
    wrapped_line_count,
)
from .schema import Diagram, Node

NEST_PADDING = 8.0
MIN_AREA_RATIO = 1.2  # a parent must be at least this much larger than the child
OVERLAP_RATIO = 0.5  # of the child's area overlapping, to count as nested


def _area(node: Node) -> float:
    return node.width * node.height


def _overlap(a: Node, b: Node) -> float:
    w = min(a.x + a.width / 2, b.x + b.width / 2) - max(a.x - a.width / 2, b.x - b.width / 2)
    h = min(a.y + a.height / 2, b.y + b.height / 2) - max(a.y - a.height / 2, b.y - b.height / 2)
    return max(w, 0.0) * max(h, 0.0)


def _expand_for_text(node: Node) -> None:
    if not node.text:
        return
    size = fitted_font_size(node)
    avail_w = max(node.width - 2 * TEXT_PADDING, 20.0)
    needed = (
        wrapped_line_count(node.text, size, avail_w) * size * LINE_HEIGHT
        + 2 * TEXT_PADDING
    )
    if needed > node.height:
        node.height = needed


def _enclosing_parent(node: Node, nodes: list[Node]) -> Node | None:
    candidates = [
        other
        for other in nodes
        if other is not node
        and _area(other) >= MIN_AREA_RATIO * _area(node)
        and _overlap(other, node) >= OVERLAP_RATIO * _area(node)
    ]
    return min(candidates, key=_area) if candidates else None


def _clamp_into(child: Node, parent: Node) -> None:
    top_reserve = NEST_PADDING
    if parent.text and parent.text_valign == "top":
        top_reserve += fitted_font_size(parent) * 1.6

    inner_w = parent.width - 2 * NEST_PADDING
    inner_h = parent.height - NEST_PADDING - top_reserve
    if inner_w <= 0 or inner_h <= 0:
        return

    child.width = min(child.width, inner_w)
    child.height = min(child.height, inner_h)

    left = parent.x - parent.width / 2 + NEST_PADDING + child.width / 2
    right = parent.x + parent.width / 2 - NEST_PADDING - child.width / 2
    top = parent.y - parent.height / 2 + top_reserve + child.height / 2
    bottom = parent.y + parent.height / 2 - NEST_PADDING - child.height / 2
    child.x = min(max(child.x, left), right)
    child.y = min(max(child.y, top), bottom)


def normalize_layout(diagram: Diagram) -> Diagram:
    nodes = [node.model_copy() for node in diagram.nodes]

    for node in nodes:
        _expand_for_text(node)

    # Largest first, so a container settles before its children clamp into it.
    for node in sorted(nodes, key=_area, reverse=True):
        parent = _enclosing_parent(node, nodes)
        if parent is not None:
            _clamp_into(node, parent)

    return Diagram(nodes=nodes, connectors=list(diagram.connectors))
