import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageFont

from report_renderer import (
    DEFAULT_FONT_PATH,
    build_font_subset_text,
    render_report_image,
)

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None


class ReportRendererTest(unittest.TestCase):
    def test_render_report_image_uses_bundled_font(self):
        self.assertTrue(DEFAULT_FONT_PATH.exists())
        ImageFont.truetype(str(DEFAULT_FONT_PATH), size=20)

        report = {
            "title": "基金申购限额日报 (A类)",
            "generated_at": "2026-05-07 13:30:00",
            "sections": [
                {
                    "title": "可申购",
                    "groups": [
                        {
                            "title": "纳斯达克100",
                            "funds": [
                                {
                                    "code": "270042",
                                    "name": "广发纳斯达克100ETF联接A",
                                    "short_name": "广发纳指100",
                                    "limit_display": "100元 ↑",
                                    "status": "开放申购",
                                    "available": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "不可申购",
                    "groups": [
                        {
                            "title": "标普500",
                            "funds": [
                                {
                                    "code": "161125",
                                    "name": "易方达标普500指数A",
                                    "short_name": "易方达标普500",
                                    "limit_display": "暂停申购",
                                    "status": "暂停申购",
                                    "available": False,
                                }
                            ],
                        }
                    ],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.png"
            render_report_image(report, output)

            self.assertGreater(output.stat().st_size, 0)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreaterEqual(image.width, 900)
                self.assertGreater(image.height, 300)

    @unittest.skipIf(TTFont is None, "fontTools is required for font coverage checks")
    def test_bundled_font_covers_current_report_text(self):
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)

        font = TTFont(str(DEFAULT_FONT_PATH))
        covered_codepoints = set()
        for table in font["cmap"].tables:
            covered_codepoints.update(table.cmap.keys())

        expected_text = build_font_subset_text(config)
        missing = sorted({char for char in expected_text if ord(char) not in covered_codepoints})

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
