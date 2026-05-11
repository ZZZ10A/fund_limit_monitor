import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor import FundMonitor


FEE_HTML = """
<html>
  <body>
    <h4>运作费用</h4>
    <table>
      <tr>
        <td>管理费率</td><td>0.80%（每年）</td>
        <td>托管费率</td><td>0.20%（每年）</td>
        <td>销售服务费率</td><td>---</td>
      </tr>
    </table>
    <h4>申购费率（前端）</h4>
    <table>
      <tr>
        <th>适用金额</th>
        <th>适用期限</th>
        <th>原费率 | 天天基金优惠费率 银行卡购买 | 活期宝购买</th>
      </tr>
      <tr>
        <td>小于50万元</td>
        <td>---</td>
        <td>1.50% | 0.15% | 0.15%</td>
      </tr>
      <tr>
        <td>大于等于500万元</td>
        <td>---</td>
        <td>每笔1000元</td>
      </tr>
    </table>
    <h4>赎回费率</h4>
    <table>
      <tr><th>适用金额</th><th>适用期限</th><th>赎回费率</th></tr>
      <tr><td>---</td><td>小于7天</td><td>1.50%</td></tr>
      <tr><td>---</td><td>大于等于365天，小于730天</td><td>0.25%</td></tr>
      <tr><td>---</td><td>大于等于730天</td><td>0.00%</td></tr>
    </table>
  </body>
</html>
"""


def make_monitor(history_db_path=None):
    monitor = object.__new__(FundMonitor)
    monitor.history_db_path = Path(history_db_path) if history_db_path else None
    if history_db_path:
        monitor._init_history_db()
    return monitor


def fund(
    code,
    limit_text,
    limit_val,
    status="开放申购",
    name=None,
):
    return {
        "code": code,
        "name": name or f"测试基金{code}A",
        "status": status,
        "limit_text": limit_text,
        "limit_val": limit_val,
    }


def flattened_report_funds(report):
    funds = {}
    for section in report["sections"]:
        for group in section["groups"]:
            for item in group["funds"]:
                funds[item["code"]] = item
    return funds


class FundMonitorHistoryTest(unittest.TestCase):
    def test_history_database_initializes_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            make_monitor(db_path)

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'fund_limit_history'
                    """
                ).fetchone()

            self.assertEqual(row[0], "fund_limit_history")

    def test_save_history_upserts_one_row_per_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")

            monitor._save_history("2026-05-11", [fund("270042", "100元", 100)])
            monitor._save_history("2026-05-11", [fund("270042", "500元", 500)])

            with sqlite3.connect(monitor.history_db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM fund_limit_history"
                ).fetchone()[0]
                limits_json = conn.execute(
                    "SELECT limits_json FROM fund_limit_history WHERE date = ?",
                    ("2026-05-11",),
                ).fetchone()[0]

            limits = json.loads(limits_json)
            self.assertEqual(count, 1)
            self.assertEqual(limits["270042"]["limit_value"], 500)
            self.assertEqual(limits["270042"]["limit_text"], "500元")

    def test_report_uses_latest_history_before_report_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")
            monitor._save_history("2026-05-09", [fund("270042", "50元", 50)])
            monitor._save_history("2026-05-10", [fund("270042", "100元", 100)])
            monitor._save_history("2026-05-11", [fund("270042", "999元", 999)])

            report = monitor.build_report(
                [fund("270042", "500元", 500)],
                generated_at="2026-05-11 13:30:00",
            )
            item = flattened_report_funds(report)["270042"]

            self.assertEqual(item["previous_limit_display"], "100元")
            self.assertEqual(item["current_limit_display"], "500元")
            self.assertEqual(item["change_direction"], "increase")
            self.assertEqual(item["change_display"], "100元 -> 500元 ↑")
            self.assertEqual(item["limit_display"], "100元 -> 500元 ↑")

    def test_empty_database_ignores_legacy_history_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                Path("history.json").write_text(
                    json.dumps({"limits": {"270042": 100}}),
                    encoding="utf-8",
                )
                monitor = make_monitor(Path(tmpdir) / "history.db")

                report = monitor.build_report(
                    [fund("270042", "500元", 500)],
                    generated_at="2026-05-11 13:30:00",
                )
                item = flattened_report_funds(report)["270042"]
            finally:
                os.chdir(old_cwd)

            self.assertEqual(item["previous_limit_display"], "")
            self.assertEqual(item["change_display"], "")
            self.assertEqual(item["limit_display"], "500元")

    def test_change_display_handles_increase_decrease_unlimited_and_paused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")
            monitor._save_history(
                "2026-05-10",
                [
                    fund("A", "100元", 100),
                    fund("B", "500元", 500),
                    fund("C", "100元", 100),
                    fund("D", "100元", 100),
                ],
            )

            report = monitor.build_report(
                [
                    fund("A", "500元", 500),
                    fund("B", "100元", 100),
                    fund("C", "None", float("inf")),
                    fund("D", "None", -1, status="暂停申购"),
                ],
                generated_at="2026-05-11 13:30:00",
            )
            items = flattened_report_funds(report)
            markdown = monitor.render_report_markdown(report)

            self.assertEqual(items["A"]["change_display"], "100元 -> 500元 ↑")
            self.assertEqual(items["B"]["change_display"], "500元 -> 100元 ↓")
            self.assertEqual(items["C"]["change_display"], "100元 -> 不限 ↑")
            self.assertEqual(items["D"]["change_display"], "100元 -> 暂停申购 ↓")
            self.assertIn("测试基金D(D) 🔴 : 100元 -> 暂停申购 ↓", markdown)


class FundMonitorFeeTest(unittest.TestCase):
    def setUp(self):
        self.monitor = make_monitor()

    def test_parse_fee_info_from_eastmoney_tables(self):
        fee_info = self.monitor._parse_fee_info_html(FEE_HTML)

        self.assertEqual(
            fee_info["operation_display"],
            "管理0.80% 托管0.20% 销售-- 合计1.00%/年",
        )
        self.assertEqual(fee_info["subscription_display"], "<50万元 0.15%")
        self.assertEqual(
            fee_info["redemption_display"],
            "<7天 1.50% / >=730天 0.00%",
        )
        self.assertEqual(fee_info["fee_error"], "")

    @patch("monitor.requests.get", side_effect=Exception("network down"))
    def test_fetch_fee_failure_returns_error_without_raising(self, _get):
        fee_info = self.monitor.fetch_fund_fee_info("270042")

        self.assertEqual(fee_info["fee_error"], "费率获取失败")
        self.assertEqual(fee_info["operation_display"], "")

    def test_markdown_includes_independent_fee_summary_section(self):
        funds_data = [
            {
                "code": "270042",
                "name": "广发纳斯达克100ETF联接A",
                "status": "开放申购",
                "limit_text": "100元",
                "limit_val": 100,
                "operation_display": "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年",
                "subscription_display": "<100万元 0.13%",
                "redemption_display": "<7天 1.50% / >=2年 0.00%",
                "fee_error": "",
            },
            {
                "code": "161125",
                "name": "易方达标普500指数A",
                "status": "暂停申购",
                "limit_text": "None",
                "limit_val": -1,
                "fee_error": "费率获取失败",
            },
        ]

        report = self.monitor.build_report(
            funds_data,
            generated_at="2026-05-11 13:30:00",
        )
        markdown = self.monitor.render_report_markdown(report)

        self.assertIn("## 费率摘要", markdown)
        self.assertIn(
            "| 基金 | 运作费用 | 申购优惠 | 赎回费率 |",
            markdown,
        )
        self.assertIn(
            "| 广发纳指100(270042) | 管理0.80% 托管0.20% 销售0.00% 合计1.00%/年 | "
            "<100万元 0.13% | <7天 1.50% / >=2年 0.00% |",
            markdown,
        )
        self.assertIn("| 易方达标普500(161125) | 费率获取失败 | -- | -- |", markdown)


if __name__ == "__main__":
    unittest.main()
