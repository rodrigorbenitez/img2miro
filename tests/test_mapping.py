"""Unit tests for the mapping layer — no network, fake Miro client."""

import unittest

from img2miro.miro_client import (
    MiroClient,
    connector_payload,
    content_html,
    fitted_font_size,
    push_diagram,
    shape_payload,
    text_payload,
)
from img2miro.schema import Connector, Diagram, Node, TextLabel


def make_node(node_id: str = "n1", **overrides) -> Node:
    fields = dict(
        id=node_id,
        shape="round_rectangle",
        text="Start",
        x=100.0,
        y=50.0,
        width=160.0,
        height=80.0,
        fill_color="#d5e8d4",
        border_color="#82b366",
        border_width=2.0,
        border_style="normal",
        text_color="#1a1a1a",
        font_size=14.0,
        font="sans",
        text_align="center",
        text_valign="middle",
    )
    fields.update(overrides)
    return Node(**fields)


def make_label(**overrides) -> TextLabel:
    fields = dict(
        text="DynamoDB",
        x=100.0,
        y=120.0,
        width=90.0,
        font_size=12.0,
        font="sans",
        color="#333333",
        text_align="center",
    )
    fields.update(overrides)
    return TextLabel(**fields)


def make_diagram(nodes=(), labels=(), connectors=()) -> Diagram:
    return Diagram(nodes=list(nodes), labels=list(labels), connectors=list(connectors))


def make_connector(**overrides) -> Connector:
    # Defaults match make_node geometry: 'a' at (100,50) 160x80 (right edge
    # x=180), 'b' assumed at (300,50) 160x80 (left edge x=220).
    fields = dict(
        from_id="a",
        to_id="b",
        from_x=180.0,
        from_y=50.0,
        to_x=220.0,
        to_y=50.0,
        start_arrow=False,
        end_arrow=True,
        label="",
        style="straight",
        stroke_color="#555555",
        stroke_style="normal",
    )
    fields.update(overrides)
    return Connector(**fields)


def make_nodes_by_id() -> dict:
    return {"a": make_node("a"), "b": make_node("b", x=300.0)}


class FakeMiroClient:
    def __init__(self):
        self.shapes: list[dict] = []
        self.texts: list[dict] = []
        self.connectors: list[dict] = []

    def create_shape(self, payload: dict) -> str:
        self.shapes.append(payload)
        return f"miro_{len(self.shapes)}"

    def create_text(self, payload: dict) -> str:
        self.texts.append(payload)
        return f"text_{len(self.texts)}"

    def create_connector(self, payload: dict) -> str:
        self.connectors.append(payload)
        return f"conn_{len(self.connectors)}"


class ContentHtmlTests(unittest.TestCase):
    def test_plain_text_wrapped_in_paragraph(self):
        self.assertEqual(content_html("Start"), "<p>Start</p>")

    def test_line_breaks_become_br(self):
        self.assertEqual(content_html("line 1\nline 2"), "<p>line 1<br>line 2</p>")

    def test_html_is_escaped(self):
        self.assertEqual(content_html("a < b & c"), "<p>a &lt; b &amp; c</p>")

    def test_empty_text(self):
        self.assertEqual(content_html(""), "")


class ShapePayloadTests(unittest.TestCase):
    def test_basic_fields(self):
        payload = shape_payload(make_node())
        self.assertEqual(payload["data"], {"shape": "round_rectangle", "content": "<p>Start</p>"})
        self.assertEqual(payload["position"], {"x": 100.0, "y": 50.0})
        self.assertEqual(payload["geometry"], {"width": 160.0, "height": 80.0})
        self.assertEqual(payload["style"]["fillColor"], "#d5e8d4")
        self.assertEqual(payload["style"]["borderColor"], "#82b366")
        self.assertEqual(payload["style"]["color"], "#1a1a1a")

    def test_opacity_quirk_always_set_as_strings(self):
        # Miro renders shapes invisible without these exact string values.
        payload = shape_payload(make_node())
        self.assertEqual(payload["style"]["fillOpacity"], "1.0")
        self.assertEqual(payload["style"]["borderOpacity"], "1.0")

    def test_text_style_fields(self):
        payload = shape_payload(make_node(font="serif", text_align="left", font_size=18.0))
        self.assertEqual(payload["style"]["fontFamily"], "pt_serif")
        self.assertEqual(payload["style"]["fontSize"], "18")
        self.assertEqual(payload["style"]["textAlign"], "left")
        self.assertEqual(payload["style"]["textAlignVertical"], "middle")

    def test_font_size_clamped_to_miro_range(self):
        self.assertEqual(shape_payload(make_node(font_size=4.0))["style"]["fontSize"], "10")
        # Empty text skips auto-fit, so only the Miro max clamp applies
        self.assertEqual(shape_payload(make_node(text="", font_size=999.0))["style"]["fontSize"], "288")

    def test_border_fields(self):
        payload = shape_payload(make_node(border_width=3.0, border_style="dashed"))
        self.assertEqual(payload["style"]["borderWidth"], "3.0")
        self.assertEqual(payload["style"]["borderStyle"], "dashed")

    def test_border_width_clamped_to_miro_range(self):
        self.assertEqual(shape_payload(make_node(border_width=0.2))["style"]["borderWidth"], "1.0")
        self.assertEqual(shape_payload(make_node(border_width=80.0))["style"]["borderWidth"], "24.0")

    def test_text_valign_from_node(self):
        payload = shape_payload(make_node(text_valign="top"))
        self.assertEqual(payload["style"]["textAlignVertical"], "top")


class FittedFontSizeTests(unittest.TestCase):
    def test_short_text_keeps_extracted_size(self):
        self.assertEqual(fitted_font_size(make_node(text="OK", font_size=14.0)), 14)

    def test_long_text_in_small_shape_shrinks(self):
        node = make_node(
            text="This is a very long label that cannot possibly fit "
            "at the extracted size inside such a small shape",
            font_size=24.0,
            width=120.0,
            height=50.0,
        )
        size = fitted_font_size(node)
        self.assertLess(size, 24)
        self.assertGreaterEqual(size, 10)

    def test_never_shrinks_below_miro_minimum(self):
        node = make_node(text="x" * 2000, font_size=14.0, width=40.0, height=30.0)
        self.assertEqual(fitted_font_size(node), 10)

    def test_empty_text_keeps_extracted_size(self):
        self.assertEqual(fitted_font_size(make_node(text="", font_size=14.0)), 14)


class TextPayloadTests(unittest.TestCase):
    def test_basic_fields(self):
        payload = text_payload(make_label())
        self.assertEqual(payload["data"], {"content": "<p>DynamoDB</p>"})
        self.assertEqual(payload["position"], {"x": 100.0, "y": 120.0})
        self.assertEqual(payload["geometry"], {"width": 90.0})
        self.assertEqual(payload["style"]["color"], "#333333")
        self.assertEqual(payload["style"]["fontSize"], "12")
        self.assertEqual(payload["style"]["fontFamily"], "open_sans")
        self.assertEqual(payload["style"]["textAlign"], "center")

    def test_font_size_clamped(self):
        self.assertEqual(text_payload(make_label(font_size=4.0))["style"]["fontSize"], "10")


class ConnectorPayloadTests(unittest.TestCase):
    def test_maps_ids_and_style(self):
        connector = make_connector(style="elbowed", stroke_color="#ff0000", stroke_style="dashed")
        payload = connector_payload(connector, {"a": "miro_1", "b": "miro_2"}, make_nodes_by_id())
        self.assertEqual(payload["startItem"]["id"], "miro_1")
        self.assertEqual(payload["endItem"]["id"], "miro_2")
        self.assertEqual(payload["shape"], "elbowed")
        self.assertEqual(payload["style"]["strokeColor"], "#ff0000")
        self.assertEqual(payload["style"]["strokeStyle"], "dashed")
        self.assertNotIn("captions", payload)

    def test_label_becomes_caption(self):
        payload = connector_payload(make_connector(label="yes"), {"a": "1", "b": "2"}, make_nodes_by_id())
        self.assertEqual(payload["captions"], [{"content": "yes"}])

    def test_exact_endpoints_become_relative_positions(self):
        # 'a' spans x 20..180, y 10..90; touching its right edge mid-height
        payload = connector_payload(make_connector(), {"a": "1", "b": "2"}, make_nodes_by_id())
        self.assertEqual(payload["startItem"]["position"], {"x": "100.0%", "y": "50.0%"})
        # 'b' spans x 220..380; touching its left edge mid-height
        self.assertEqual(payload["endItem"]["position"], {"x": "0.0%", "y": "50.0%"})

    def test_endpoints_outside_bounds_are_clamped(self):
        payload = connector_payload(
            make_connector(from_x=0.0, from_y=200.0), {"a": "1", "b": "2"}, make_nodes_by_id()
        )
        self.assertEqual(payload["startItem"]["position"], {"x": "0.0%", "y": "100.0%"})

    def test_arrowheads_map_to_stroke_caps(self):
        payload = connector_payload(make_connector(), {"a": "1", "b": "2"}, make_nodes_by_id())
        self.assertEqual(payload["style"]["startStrokeCap"], "none")
        self.assertEqual(payload["style"]["endStrokeCap"], "stealth")

    def test_double_headed_arrow(self):
        connector = make_connector(start_arrow=True, end_arrow=True)
        payload = connector_payload(connector, {"a": "1", "b": "2"}, make_nodes_by_id())
        self.assertEqual(payload["style"]["startStrokeCap"], "stealth")
        self.assertEqual(payload["style"]["endStrokeCap"], "stealth")

    def test_parallel_arrows_keep_distinct_attachment_points(self):
        forward = make_connector(from_y=30.0, to_y=30.0)
        feedback = make_connector(
            from_id="b", to_id="a", from_x=220.0, from_y=70.0, to_x=180.0, to_y=70.0
        )
        id_map, nodes = {"a": "1", "b": "2"}, make_nodes_by_id()
        p_fwd = connector_payload(forward, id_map, nodes)
        p_back = connector_payload(feedback, id_map, nodes)
        self.assertNotEqual(
            p_fwd["startItem"]["position"], p_back["endItem"]["position"]
        )
        self.assertEqual(p_fwd["startItem"]["position"]["y"], "25.0%")
        self.assertEqual(p_back["endItem"]["position"]["y"], "75.0%")


class PushDiagramTests(unittest.TestCase):
    def test_pushes_shapes_then_connectors(self):
        diagram = make_diagram(
            nodes=[make_node("a"), make_node("b", x=300.0)],
            connectors=[make_connector(style="curved")],
        )
        client = FakeMiroClient()
        id_map, created, skipped = push_diagram(client, diagram)

        self.assertEqual(id_map, {"a": "miro_1", "b": "miro_2"})
        self.assertEqual(created, 1)
        self.assertEqual(skipped, [])
        self.assertEqual(client.connectors[0]["startItem"]["id"], "miro_1")
        self.assertEqual(client.connectors[0]["endItem"]["id"], "miro_2")

    def test_labels_created_as_text_items(self):
        diagram = make_diagram(
            nodes=[make_node("icon", text="")],
            labels=[make_label()],
        )
        client = FakeMiroClient()
        push_diagram(client, diagram)
        self.assertEqual(len(client.texts), 1)
        self.assertEqual(client.texts[0]["data"]["content"], "<p>DynamoDB</p>")

    def test_containers_created_before_children_for_z_order(self):
        container = make_node("box", width=800.0, height=600.0, text_valign="top")
        child = make_node("leaf", width=100.0, height=60.0)
        diagram = make_diagram(nodes=[child, container])
        client = FakeMiroClient()
        id_map, _, _ = push_diagram(client, diagram)

        # Largest shape first regardless of extraction order
        self.assertEqual(client.shapes[0]["geometry"], {"width": 800.0, "height": 600.0})
        self.assertEqual(client.shapes[1]["geometry"], {"width": 100.0, "height": 60.0})
        # id_map still maps both correctly
        self.assertEqual(id_map["box"], "miro_1")
        self.assertEqual(id_map["leaf"], "miro_2")

    def test_skips_connectors_with_unknown_endpoints(self):
        diagram = make_diagram(
            nodes=[make_node("a")],
            connectors=[make_connector(to_id="ghost")],
        )
        client = FakeMiroClient()
        _, created, skipped = push_diagram(client, diagram)

        self.assertEqual(created, 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(client.connectors, [])


class FocusUrlTests(unittest.TestCase):
    def test_focus_url_appends_move_to_widget(self):
        client = MiroClient("token", "uXjVHOXBGe8=")
        self.assertEqual(
            client.focus_url("3458764675979129032"),
            "https://miro.com/app/board/uXjVHOXBGe8=/?moveToWidget=3458764675979129032",
        )

    def test_focus_url_falls_back_to_bare_url_without_item(self):
        client = MiroClient("token", "uXjVHOXBGe8=")
        self.assertEqual(client.focus_url(None), "https://miro.com/app/board/uXjVHOXBGe8=/")


if __name__ == "__main__":
    unittest.main()
