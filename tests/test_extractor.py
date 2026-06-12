"""Unit tests for the extractor: input handling, JSON parsing, and the
agent layer faked out — no network, no Claude Code CLI."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from img2miro.extractor import (
    EXTRACT_PROMPT,
    MAX_SVG_BYTES,
    _agent_output,
    _parse_diagram,
    _source_part,
    _stderr_suffix,
    extract,
)
from img2miro.schema import Diagram

NODE = {
    "id": "n1",
    "shape": "rectangle",
    "text": "Login",
    "x": 100.0,
    "y": 50.0,
    "width": 120.0,
    "height": 60.0,
    "fill_color": "#ffffff",
    "border_color": "#1a1a1a",
    "border_width": 2.0,
    "border_style": "normal",
    "text_color": "#1a1a1a",
    "font_size": 14.0,
    "font": "sans",
    "text_align": "center",
    "text_valign": "middle",
}
DIAGRAM_DICT = {"nodes": [NODE], "labels": [], "connectors": []}
DIAGRAM_JSON = json.dumps(DIAGRAM_DICT)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name: str, data) -> Path:
        path = self.dir / name
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path


class SourcePartTests(TempDirTestCase):
    def test_png_references_path_and_read_tool(self):
        path = self.write("d.png", b"\x89PNG fake")
        part = _source_part(path)
        self.assertIn(str(path.resolve()), part)
        self.assertIn("Read tool", part)

    def test_svg_embeds_source_markup(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10" fill="#ff0000"/></svg>'
        part = _source_part(self.write("d.svg", svg))
        self.assertIn(svg, part)
        self.assertIn("SVG source code", part)

    def test_oversized_svg_rejected_with_guidance(self):
        path = self.write("big.svg", "<svg>" + "x" * MAX_SVG_BYTES + "</svg>")
        with self.assertRaises(ValueError) as ctx:
            _source_part(path)
        self.assertIn("PNG", str(ctx.exception))

    def test_unsupported_suffix_lists_svg_as_supported(self):
        path = self.write("d.bmp", b"BM fake")
        with self.assertRaises(ValueError) as ctx:
            _source_part(path)
        self.assertIn(".svg", str(ctx.exception))


class ParseDiagramTests(unittest.TestCase):
    def test_bare_json_parses(self):
        diagram = _parse_diagram(DIAGRAM_JSON)
        self.assertIsInstance(diagram, Diagram)
        self.assertEqual(diagram.nodes[0].id, "n1")

    def test_fenced_json_parses(self):
        diagram = _parse_diagram(f"```json\n{DIAGRAM_JSON}\n```")
        self.assertEqual(diagram.nodes[0].text, "Login")

    def test_json_with_surrounding_prose_parses(self):
        text = f"Here is the extraction:\n{DIAGRAM_JSON}\nLet me know!"
        diagram = _parse_diagram(text)
        self.assertEqual(len(diagram.nodes), 1)

    def test_invalid_json_raises_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            _parse_diagram("I could not process this image, sorry.")
        self.assertIn("valid JSON", str(ctx.exception))

    def test_schema_violation_raises_clear_error(self):
        bad = json.dumps({"nodes": "not-a-list", "labels": [], "connectors": []})
        with self.assertRaises(RuntimeError) as ctx:
            _parse_diagram(bad)
        self.assertIn("schema", str(ctx.exception))


class ExtractTests(TempDirTestCase):
    def test_extract_without_refine_makes_one_call(self):
        image = self.write("d.png", b"\x89PNG fake")
        with patch(
            "img2miro.extractor._agent_output", return_value=DIAGRAM_JSON
        ) as agent:
            diagram = extract(image, refine=False)
        self.assertEqual(agent.call_count, 1)
        prompt = agent.call_args.args[0]
        self.assertIn(str(image.resolve()), prompt)
        self.assertIn(EXTRACT_PROMPT, prompt)
        self.assertEqual(diagram.nodes[0].id, "n1")

    def test_refine_makes_second_call_with_first_result(self):
        image = self.write("d.png", b"\x89PNG fake")
        with patch(
            "img2miro.extractor._agent_output", return_value=DIAGRAM_JSON
        ) as agent:
            extract(image, refine=True)
        self.assertEqual(agent.call_count, 2)
        refine_prompt = agent.call_args_list[1].args[0]
        self.assertIn('"Login"', refine_prompt)

    def test_structured_output_dict_is_validated(self):
        image = self.write("d.png", b"\x89PNG fake")
        with patch("img2miro.extractor._agent_output", return_value=DIAGRAM_DICT):
            diagram = extract(image, refine=False)
        self.assertEqual(diagram.nodes[0].text, "Login")

    def test_invalid_agent_response_surfaces_error(self):
        image = self.write("d.png", b"\x89PNG fake")
        with patch("img2miro.extractor._agent_output", return_value="not json"):
            with self.assertRaises(RuntimeError):
                extract(image, refine=False)


class StderrSuffixTests(unittest.TestCase):
    def test_empty_lines_produce_no_suffix(self):
        self.assertEqual(_stderr_suffix([]), "")
        self.assertEqual(_stderr_suffix(["", "  "]), "")

    def test_lines_are_appended_under_a_header(self):
        suffix = _stderr_suffix(["model not found", "exiting"])
        self.assertIn("Claude Code CLI said:", suffix)
        self.assertIn("model not found", suffix)


class AgentOutputErrorTests(unittest.TestCase):
    """`asyncio.run` is faked; close the `_run()` coroutine it receives so the
    test doesn't leak an un-awaited coroutine."""

    @staticmethod
    def _fake_run(*, raises=None, returns=None):
        def run(coro):
            coro.close()
            if raises is not None:
                raise raises
            return returns

        return run

    def test_bare_sdk_exception_is_wrapped_not_raw(self):
        # The SDK raises a plain Exception from its message stream when the CLI
        # exits non-zero; we must surface it as a clean RuntimeError.
        boom = Exception("Claude Code returned an error result: success")
        with patch("img2miro.extractor.asyncio.run", self._fake_run(raises=boom)):
            with self.assertRaises(RuntimeError) as ctx:
                _agent_output("prompt", "claude-fable-5", Path("."))
        msg = str(ctx.exception)
        self.assertIn("agent failed", msg)
        self.assertIn("error result", msg)

    def test_missing_result_raises_clear_error(self):
        with patch("img2miro.extractor.asyncio.run", self._fake_run(returns=None)):
            with self.assertRaises(RuntimeError) as ctx:
                _agent_output("prompt", "claude-fable-5", Path("."))
        self.assertIn("without producing a result", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
