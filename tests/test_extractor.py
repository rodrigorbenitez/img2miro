"""Unit tests for input handling in the extractor — no network."""

import tempfile
import unittest
from pathlib import Path

from img2miro.extractor import MAX_SVG_BYTES, _source_block


class SourceBlockTests(unittest.TestCase):
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

    def test_png_becomes_base64_image_block(self):
        path = self.write("d.png", b"\x89PNG fake")
        block = _source_block(path)
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["type"], "base64")
        self.assertEqual(block["source"]["media_type"], "image/png")

    def test_svg_becomes_text_block_with_source(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10" fill="#ff0000"/></svg>'
        block = _source_block(self.write("d.svg", svg))
        self.assertEqual(block["type"], "text")
        self.assertIn(svg, block["text"])
        self.assertIn("SVG source code", block["text"])

    def test_oversized_svg_rejected_with_guidance(self):
        path = self.write("big.svg", "<svg>" + "x" * MAX_SVG_BYTES + "</svg>")
        with self.assertRaises(ValueError) as ctx:
            _source_block(path)
        self.assertIn("PNG", str(ctx.exception))

    def test_unsupported_suffix_lists_svg_as_supported(self):
        path = self.write("d.bmp", b"BM fake")
        with self.assertRaises(ValueError) as ctx:
            _source_block(path)
        self.assertIn(".svg", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
