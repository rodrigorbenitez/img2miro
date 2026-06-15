"""Unit tests for the extractor: input handling, JSON parsing, and the
agent layer faked out — no network, no Claude Code CLI."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import ResultMessage

from img2miro.extractor import (
    EXTRACT_PROMPT,
    MAX_SVG_BYTES,
    _agent_output,
    _parse_diagram,
    _result_failure_message,
    _source_block,
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


class SourceBlockTests(TempDirTestCase):
    def test_png_becomes_base64_image_block(self):
        block = _source_block(self.write("d.png", b"\x89PNG fake"))
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["media_type"], "image/png")
        self.assertTrue(block["source"]["data"])

    def test_svg_becomes_text_block_with_markup(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        block = _source_block(self.write("d.svg", svg))
        self.assertEqual(block["type"], "text")
        self.assertIn(svg, block["text"])

    def test_unsupported_suffix_rejected(self):
        with self.assertRaises(ValueError):
            _source_block(self.write("d.bmp", b"BM fake"))


class ApiBackendTests(TempDirTestCase):
    def test_api_backend_calls_api_output_not_agent(self):
        image = self.write("d.png", b"\x89PNG fake")
        with patch(
            "img2miro.extractor._api_output", return_value=DIAGRAM_JSON
        ) as api, patch("img2miro.extractor._agent_output") as agent:
            diagram = extract(image, refine=False, backend="api")
        api.assert_called_once()
        agent.assert_not_called()
        # The diagram travels as a content block, not a Read-tool path prompt.
        content = api.call_args.args[0]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(diagram.nodes[0].id, "n1")


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


def _result_message(**overrides) -> ResultMessage:
    fields = dict(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s1",
    )
    fields.update(overrides)
    return ResultMessage(**fields)


def _fake_query(*messages, then_raise=None):
    """Build a stand-in for extractor.query: an async generator that yields the
    given messages, then optionally raises (mimicking the SDK's stream error
    after a non-zero CLI exit)."""

    def factory(*args, **kwargs):
        async def gen():
            for m in messages:
                yield m
            if then_raise is not None:
                raise then_raise

        return gen()

    return factory


class ResultFailureMessageTests(unittest.TestCase):
    def test_surfaces_subtype_stop_reason_and_model_text(self):
        rm = _result_message(
            is_error=True,
            subtype="success",
            stop_reason="refusal",
            result="I can't read that image.",
        )
        msg = _result_failure_message(rm, [])
        self.assertIn("subtype=success", msg)
        self.assertIn("stop_reason=refusal", msg)
        self.assertIn("I can't read that image.", msg)

    def test_surfaces_denied_tools(self):
        rm = _result_message(is_error=True, permission_denials=["Read"])
        self.assertIn("denied_tools", _result_failure_message(rm, []))

    def test_appends_captured_stderr(self):
        rm = _result_message(is_error=True)
        msg = _result_failure_message(rm, ["model not found"])
        self.assertIn("Claude Code CLI said:", msg)
        self.assertIn("model not found", msg)


class AgentOutputErrorTests(unittest.TestCase):
    def test_error_result_yielded_before_stream_raises_is_reported(self):
        # The SDK yields the error result, then raises from the stream; we must
        # report the result's real fields, not the opaque wrapper.
        rm = _result_message(
            is_error=True, subtype="success", result="schema validation failed"
        )
        boom = Exception("Claude Code returned an error result: success")
        with patch("img2miro.extractor.query", _fake_query(rm, then_raise=boom)):
            with self.assertRaises(RuntimeError) as ctx:
                _agent_output("prompt", "claude-fable-5", Path("."))
        msg = str(ctx.exception)
        self.assertIn("Extraction failed", msg)
        self.assertIn("schema validation failed", msg)

    def test_bare_sdk_exception_with_no_result_is_wrapped(self):
        boom = Exception("Claude Code returned an error result: success")
        with patch("img2miro.extractor.query", _fake_query(then_raise=boom)):
            with self.assertRaises(RuntimeError) as ctx:
                _agent_output("prompt", "claude-fable-5", Path("."))
        msg = str(ctx.exception)
        self.assertIn("agent failed", msg)
        self.assertIn("error result", msg)

    def test_missing_result_raises_clear_error(self):
        with patch("img2miro.extractor.query", _fake_query()):
            with self.assertRaises(RuntimeError) as ctx:
                _agent_output("prompt", "claude-fable-5", Path("."))
        self.assertIn("without producing a result", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
