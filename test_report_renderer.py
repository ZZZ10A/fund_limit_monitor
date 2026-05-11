import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from report_renderer import (
    DEFAULT_FONT_PATH,
    _build_index_tables,
    _wrap_text,
    build_font_subset_text,
    render_report_image,
)

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None


class ReportRendererTest(unittest.TestCase):
    def _sample_report(self):
        return {
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
                                    "limit_display": "100元 -> 500元 ↑",
                                    "previous_limit_display": "100元",
                                    "current_limit_display": "500元",
                                    "change_direction": "increase",
                                    "change_display": "100元 -> 500元 ↑",
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
            "fee_groups": [
                {
                    "title": "纳斯达克100",
                    "funds": [
                        {
                            "code": "270042",
                            "name": "广发纳斯达克100ETF联接A",
                            "short_name": "广发纳指100",
                            "operation_display": "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年",
                            "subscription_display": "<100万元 0.13%",
                            "redemption_display": "<7天 1.50% / >=2年 0.00%",
                            "fee_error": "",
                        }
                    ],
                },
                {
                    "title": "标普500",
                    "funds": [
                        {
                            "code": "161125",
                            "name": "易方达标普500指数A",
                            "short_name": "易方达标普500",
                            "operation_display": "",
                            "subscription_display": "",
                            "redemption_display": "",
                            "fee_error": "费率获取失败",
                        }
                    ],
                },
            ],
        }

    def test_render_report_image_uses_bundled_font(self):
        self.assertTrue(DEFAULT_FONT_PATH.exists())
        ImageFont.truetype(str(DEFAULT_FONT_PATH), size=20)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.png"
            render_report_image(self._sample_report(), output)

            self.assertGreater(output.stat().st_size, 0)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreaterEqual(image.width, 1300)
                self.assertGreater(image.height, 500)

    def test_index_tables_merge_limit_and_fee_info(self):
        tables = _build_index_tables(self._sample_report())

        self.assertEqual(
            [table["title"] for table in tables],
            ["纳斯达克100", "标普500"],
        )
        self.assertEqual(tables[0]["summary"], "可申购: 1 / 不可申购: 0")
        self.assertEqual(tables[1]["summary"], "可申购: 0 / 不可申购: 1")
        self.assertEqual(
            tables[0]["rows"][0]["name"],
            "广发纳斯达克100ETF联接A(270042)",
        )
        self.assertEqual(tables[0]["rows"][0]["spread"], "可申购\n100元 -> 500元 ↑")
        self.assertEqual(
            tables[0]["rows"][0]["operation"],
            "管理0.80% 托管0.20%\n销售0.00% 合计1.00%/年",
        )
        self.assertEqual(tables[0]["rows"][0]["subscription"], "<100万元\n0.13%")
        self.assertEqual(
            tables[0]["rows"][0]["redemption"],
            "<7天 1.50%\n>=2年 0.00%",
        )
        self.assertEqual(tables[1]["rows"][0]["spread"], "不可申购\n暂停申购")
        self.assertEqual(tables[1]["rows"][0]["operation"], "费率获取失败")
        self.assertEqual(tables[1]["rows"][0]["subscription"], "--")

    def test_cell_wrapping_keeps_complete_copy(self):
        font = ImageFont.truetype(str(DEFAULT_FONT_PATH), size=17)
        draw = ImageDraw.Draw(Image.new("RGB", (300, 1), "#ffffff"))
        text = "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年"

        lines = _wrap_text(draw, text, font, 120)

        self.assertGreater(len(lines), 1)
        self.assertNotIn("...", "".join(lines))
        self.assertEqual(
            "".join(lines).replace(" ", ""),
            text.replace(" ", ""),
        )

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
