"""Unit tests for the mapping layer — no network, fake Miro client."""

import unittest

from img2miro.miro_client import connector_payload, push_diagram, shape_payload
from img2miro.schema import Connector, Diagram, Node


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
        text_color="#1a1a1a",
    )
    fields.update(overrides)
    return Node(**fields)


class FakeMiroClient:
    def __init__(self):
        self.shapes: list[dict] = []
        self.connectors: list[dict] = []

    def create_shape(self, payload: dict) -> str:
        self.shapes.append(payload)
        return f"miro_{len(self.shapes)}"

    def create_connector(self, payload: dict) -> str:
        self.connectors.append(payload)
        return f"conn_{len(self.connectors)}"


class ShapePayloadTests(unittest.TestCase):
    def test_basic_fields(self):
        payload = shape_payload(make_node())
        self.assertEqual(payload["data"], {"shape": "round_rectangle", "content": "Start"})
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


class ConnectorPayloadTests(unittest.TestCase):
    def test_maps_ids_and_style(self):
        connector = Connector(from_id="a", to_id="b", label="", style="elbowed")
        payload = connector_payload(connector, {"a": "miro_1", "b": "miro_2"})
        self.assertEqual(payload["startItem"], {"id": "miro_1"})
        self.assertEqual(payload["endItem"], {"id": "miro_2"})
        self.assertEqual(payload["shape"], "elbowed")
        self.assertNotIn("captions", payload)

    def test_label_becomes_caption(self):
        connector = Connector(from_id="a", to_id="b", label="yes", style="straight")
        payload = connector_payload(connector, {"a": "1", "b": "2"})
        self.assertEqual(payload["captions"], [{"content": "yes"}])


class PushDiagramTests(unittest.TestCase):
    def test_pushes_shapes_then_connectors(self):
        diagram = Diagram(
            nodes=[make_node("a"), make_node("b", x=300.0)],
            connectors=[Connector(from_id="a", to_id="b", label="", style="curved")],
        )
        client = FakeMiroClient()
        id_map, created, skipped = push_diagram(client, diagram)

        self.assertEqual(id_map, {"a": "miro_1", "b": "miro_2"})
        self.assertEqual(created, 1)
        self.assertEqual(skipped, [])
        self.assertEqual(client.connectors[0]["startItem"], {"id": "miro_1"})
        self.assertEqual(client.connectors[0]["endItem"], {"id": "miro_2"})

    def test_skips_connectors_with_unknown_endpoints(self):
        diagram = Diagram(
            nodes=[make_node("a")],
            connectors=[Connector(from_id="a", to_id="ghost", label="", style="straight")],
        )
        client = FakeMiroClient()
        _, created, skipped = push_diagram(client, diagram)

        self.assertEqual(created, 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(client.connectors, [])


if __name__ == "__main__":
    unittest.main()
