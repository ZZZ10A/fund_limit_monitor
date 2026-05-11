import unittest
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


class FundMonitorFeeTest(unittest.TestCase):
    def setUp(self):
        self.monitor = object.__new__(FundMonitor)
        self.monitor.history = {"limits": {}}

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
