"""Unit tests for post-extraction layout normalization."""

import unittest

from img2miro.layout import normalize_layout

from test_mapping import make_diagram, make_node


def bounds(node):
    return (
        node.x - node.width / 2,
        node.y - node.height / 2,
        node.x + node.width / 2,
        node.y + node.height / 2,
    )


class ExpandForTextTests(unittest.TestCase):
    def test_short_text_keeps_geometry(self):
        diagram = make_diagram(nodes=[make_node(text="OK")])
        result = normalize_layout(diagram)
        self.assertEqual(result.nodes[0].width, 160.0)
        self.assertEqual(result.nodes[0].height, 80.0)

    def test_overflowing_text_grows_height(self):
        # Even at Miro's minimum font size this cannot fit a 30px-tall shape.
        diagram = make_diagram(
            nodes=[make_node(text="word " * 60, width=120.0, height=30.0)],
        )
        result = normalize_layout(diagram)
        self.assertGreater(result.nodes[0].height, 30.0)

    def test_growth_is_capped_to_avoid_overlapping_neighbours(self):
        diagram = make_diagram(
            nodes=[make_node(text="word " * 60, width=120.0, height=30.0)],
        )
        result = normalize_layout(diagram)
        self.assertLessEqual(result.nodes[0].height, 60.0)

    def test_empty_icon_squares_never_grow(self):
        # Icon/logo placeholders carry no text; their caption is a label.
        icon = make_node("icon", text="", width=48.0, height=48.0)
        result = normalize_layout(make_diagram(nodes=[icon]))
        self.assertEqual(result.nodes[0].width, 48.0)
        self.assertEqual(result.nodes[0].height, 48.0)

    def test_original_diagram_not_mutated(self):
        node = make_node(text="word " * 60, width=120.0, height=30.0)
        normalize_layout(make_diagram(nodes=[node]))
        self.assertEqual(node.height, 30.0)


class NestingTests(unittest.TestCase):
    def test_mostly_inside_child_is_clamped_fully_inside(self):
        container = make_node(
            "box", text="Group", x=400.0, y=300.0, width=600.0, height=400.0,
            text_valign="top",
        )
        # Center inside the container but right edge sticking out
        child = make_node("leaf", text="A", x=680.0, y=300.0, width=100.0, height=60.0)
        result = normalize_layout(make_diagram(nodes=[container, child]))

        boxes = {n.id: n for n in result.nodes}
        cl, ct, cr, cb = bounds(boxes["leaf"])
        pl, pt, pr, pb = bounds(boxes["box"])
        self.assertGreaterEqual(cl, pl)
        self.assertLessEqual(cr, pr)
        self.assertGreaterEqual(ct, pt)
        self.assertLessEqual(cb, pb)

    def test_child_pushed_below_container_title(self):
        container = make_node(
            "box", text="Title", x=400.0, y=300.0, width=600.0, height=400.0,
            text_valign="top", font_size=20.0,
        )
        # Child overlapping the title strip at the very top of the container
        child = make_node("leaf", text="A", x=400.0, y=105.0, width=100.0, height=60.0)
        result = normalize_layout(make_diagram(nodes=[container, child]))

        boxes = {n.id: n for n in result.nodes}
        child_top = boxes["leaf"].y - boxes["leaf"].height / 2
        container_top = boxes["box"].y - boxes["box"].height / 2
        # Top of the child must clear the reserved title strip
        self.assertGreater(child_top, container_top + 20.0)

    def test_separate_shapes_untouched(self):
        a = make_node("a", x=100.0, y=100.0)
        b = make_node("b", x=500.0, y=100.0)
        result = normalize_layout(make_diagram(nodes=[a, b]))
        boxes = {n.id: n for n in result.nodes}
        self.assertEqual((boxes["a"].x, boxes["a"].y), (100.0, 100.0))
        self.assertEqual((boxes["b"].x, boxes["b"].y), (500.0, 100.0))

    def test_similar_size_overlap_is_not_treated_as_nesting(self):
        # Two same-size shapes overlapping; neither is a container.
        a = make_node("a", x=100.0, y=100.0)
        b = make_node("b", x=140.0, y=100.0)
        result = normalize_layout(make_diagram(nodes=[a, b]))
        boxes = {n.id: n for n in result.nodes}
        self.assertEqual(boxes["a"].x, 100.0)
        self.assertEqual(boxes["b"].x, 140.0)


if __name__ == "__main__":
    unittest.main()
