import argparse
import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from notifier import build_notifier
from report_renderer import render_report_image


class FundMonitor:
    CONFIG_FILE = "config.json"
    HISTORY_FILE = "history.json"
    REPORT_TITLE = "基金申购限额日报 (A类)"
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.114 Safari/537.36"
        )
    }

    def __init__(self):
        self.config = self._load_json(self.CONFIG_FILE)
        self.history = self._load_json(self.HISTORY_FILE)
        self.notifier = build_notifier(self.config)
        self.funds_config = self.config.get("funds", [])

    def _load_json(self, filename):
        if not os.path.exists(filename):
            return {}
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return {}

    def _save_json(self, filename, data):
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _save_history(self, data):
        with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _parse_amount(self, text):
        """Parse amount text to numeric value."""
        if not text or text == "None":
            return 0

        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            return 0

        num = float(match.group(1))

        if "千万" in text:
            num *= 10000000
        elif "万" in text:
            num *= 10000

        return int(num)

    def _shorten_name(self, name):
        name = name.replace("纳斯达克100", "纳指100")
        keywords = ["ETF联接", "指数", "发起式", "发起", "精选", "股票", "(LOF)"]
        for kw in keywords:
            name = name.replace(kw, "")
        if name.endswith("A"):
            name = name[:-1]
        return name

    def _get_index_type(self, name):
        if "纳斯达克" in name or "纳指" in name:
            return "纳斯达克100"
        if "标普" in name:
            return "标普500"
        return "其他"

    def fetch_fund_info(self, code, name):
        url = f"http://fund.eastmoney.com/f10/jbgk_{code}.html"

        info = {
            "code": code,
            "name": name,
            "status": "Unknown",
            "limit_text": "None",
            "limit_val": -1,
        }

        try:
            resp = requests.get(url, headers=self.REQUEST_HEADERS, timeout=10)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            full_text = soup.get_text()

            status_match = re.search(r"交易状态：\s*(\S+)", full_text)
            if status_match:
                info["status"] = status_match.group(1)
            else:
                th = soup.find(
                    lambda tag: tag.name in ["th", "td"]
                    and "交易状态" in tag.get_text()
                )
                if th and th.find_next_sibling("td"):
                    info["status"] = th.find_next_sibling("td").get_text(strip=True)

            limit_match = re.search(r"（(.*单日.*上限.*)）", resp.text)
            if limit_match:
                raw_limit = limit_match.group(1)
                clean_limit = re.sub(r"<[^>]+>", "", raw_limit)
                info["limit_text"] = (
                    re.sub(r"单日.*?上限", "", clean_limit)
                    .replace("（", "")
                    .replace("）", "")
                )

            if "暂停" in info["status"]:
                info["limit_val"] = -1
            elif info["limit_text"] != "None":
                info["limit_val"] = self._parse_amount(info["limit_text"])
            else:
                info["limit_val"] = float("inf")

        except Exception as e:
            print(f"Error fetching {code}: {e}")

        return info

    def fetch_fund_fee_info(self, code):
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"

        try:
            resp = requests.get(url, headers=self.REQUEST_HEADERS, timeout=10)
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code}")
            resp.encoding = "utf-8"
            return self._parse_fee_info_html(resp.text)
        except Exception as e:
            print(f"Error fetching fee info for {code}: {e}")
            return self._fee_error_info()

    def _parse_fee_info_html(self, html):
        soup = BeautifulSoup(html, "html.parser")
        operation_display = self._parse_operation_fee(soup)
        subscription_display = self._parse_subscription_fee(soup)
        redemption_display = self._parse_redemption_fee(soup)

        if not (operation_display and subscription_display and redemption_display):
            raise ValueError("Incomplete fee data")

        return {
            "operation_display": operation_display,
            "subscription_display": subscription_display,
            "redemption_display": redemption_display,
            "fee_error": "",
        }

    def _fee_error_info(self):
        return {
            "operation_display": "",
            "subscription_display": "",
            "redemption_display": "",
            "fee_error": "费率获取失败",
        }

    def _parse_operation_fee(self, soup):
        table = self._find_fee_table(soup, "运作费用")
        rows = self._table_rows(table)
        if not rows:
            return ""

        pairs = {}
        for row in rows:
            for i in range(0, len(row) - 1, 2):
                pairs[row[i]] = self._normalize_fee_value(row[i + 1])

        items = [
            ("管理费率", "管理"),
            ("托管费率", "托管"),
            ("销售服务费率", "销售"),
        ]
        displays = []
        parsed_rates = []
        for source_label, display_label in items:
            value = pairs.get(source_label, "--")
            displays.append(f"{display_label}{value}")
            rate = self._parse_percent(value)
            if rate is not None:
                parsed_rates.append(rate)

        total = f"{sum(parsed_rates):.2f}%/年" if parsed_rates else "--"
        return " ".join(displays + [f"合计{total}"])

    def _parse_subscription_fee(self, soup):
        table = self._find_fee_table(soup, "申购费率")
        rows = self._data_rows(self._table_rows(table))
        if not rows:
            return ""

        row = rows[0]
        amount = self._compact_fee_range(row[0]) if row else ""
        fee = self._preferred_subscription_fee(row)
        if not fee:
            return ""
        return f"{amount} {fee}".strip()

    def _parse_redemption_fee(self, soup):
        table = self._find_fee_table(soup, "赎回费率")
        rows = self._data_rows(self._table_rows(table))
        if not rows:
            return ""

        first = self._redemption_tier_display(rows[0])
        last = self._redemption_tier_display(rows[-1])
        if not first:
            return ""
        if last and last != first:
            return f"{first} / {last}"
        return first

    def _find_fee_table(self, soup, title_keyword):
        heading = soup.find(
            lambda tag: tag.name in ["h3", "h4"]
            and title_keyword in self._clean_text(tag.get_text(" ", strip=True))
        )
        return heading.find_next("table") if heading else None

    def _table_rows(self, table):
        if not table:
            return []

        rows = []
        for tr in table.find_all("tr"):
            cells = [
                self._clean_text(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["th", "td"])
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        return rows

    def _data_rows(self, rows):
        return [
            row
            for row in rows
            if not any("适用金额" in cell or "适用期限" in cell for cell in row)
        ]

    def _preferred_subscription_fee(self, row):
        fee_cells = row[2:] if len(row) > 2 else row[1:]
        values = self._split_fee_values(fee_cells)

        if len(values) >= 2:
            return self._normalize_fee_value(values[1])

        for value in values:
            value = self._normalize_fee_value(value)
            if self._is_fee_value(value):
                return value
        return ""

    def _redemption_tier_display(self, row):
        if len(row) >= 3:
            term = row[1]
            rate = row[2]
        elif len(row) >= 2:
            term = row[0]
            rate = row[1]
        else:
            return ""

        term = self._compact_fee_range(term)
        rate = self._normalize_fee_value(rate)
        if not term or not self._is_fee_value(rate):
            return ""
        return f"{term} {rate}"

    def _split_fee_values(self, values):
        parts = []
        for value in values:
            for part in re.split(r"\s*\|\s*", value):
                part = self._clean_text(part)
                if part:
                    parts.append(part)
        return parts

    def _normalize_fee_value(self, value):
        value = self._clean_text(value)
        if not value or value == "---":
            return "--"

        percent = re.search(r"\d+(?:\.\d+)?%", value)
        if percent:
            return percent.group(0)

        fixed_fee = re.search(r"每笔\s*\d+(?:\.\d+)?\s*元", value)
        if fixed_fee:
            return re.sub(r"\s+", "", fixed_fee.group(0))

        return value

    def _parse_percent(self, value):
        match = re.search(r"(\d+(?:\.\d+)?)%", value or "")
        if not match:
            return None
        return float(match.group(1))

    def _is_fee_value(self, value):
        return bool(re.search(r"\d+(?:\.\d+)?%|每笔\d+(?:\.\d+)?元", value or ""))

    def _compact_fee_range(self, text):
        text = self._clean_text(text)
        if not text or text == "---":
            return ""

        replacements = [
            ("大于等于", ">="),
            ("小于等于", "<="),
            ("大于", ">"),
            ("小于", "<"),
            ("，", ","),
        ]
        for source, target in replacements:
            text = text.replace(source, target)
        return text

    def _clean_text(self, text):
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def build_report(self, funds_data, generated_at=None):
        limit_sorted_funds = sorted(
            funds_data,
            key=lambda x: x["limit_val"],
            reverse=True,
        )
        generated_at = generated_at or time.strftime("%Y-%m-%d %H:%M:%S")

        groups = {
            "可申购": {"纳斯达克100": [], "标普500": [], "其他": []},
            "不可申购": {"纳斯达克100": [], "标普500": [], "其他": []},
        }

        for info in limit_sorted_funds:
            is_paused = "暂停" in info["status"]
            category = (
                "不可申购" if (is_paused or info["limit_val"] == 0) else "可申购"
            )

            idx_type = self._get_index_type(info["name"])
            group_name = idx_type if idx_type in groups[category] else "其他"
            groups[category][group_name].append(info)

        last_limits = self.history.get("limits", {})
        sections = []

        for title in ["可申购", "不可申购"]:
            section = self._build_report_section(title, groups[title], last_limits)
            if section:
                sections.append(section)

        return {
            "title": self.REPORT_TITLE,
            "generated_at": generated_at,
            "sections": sections,
            "fee_groups": self._build_fee_groups(funds_data),
        }

    def _build_report_section(self, title, grouped_funds, last_limits):
        total_count = sum(len(v) for v in grouped_funds.values())
        if total_count == 0:
            return None

        section = {"title": title, "groups": []}

        for idx_name in ["纳斯达克100", "标普500", "其他"]:
            funds = grouped_funds.get(idx_name, [])
            if not funds:
                continue

            group = {"title": idx_name, "funds": []}
            for fund in funds:
                group["funds"].append(
                    self._build_report_fund(title, fund, last_limits)
                )
            section["groups"].append(group)

        return section

    def _build_report_fund(self, section_title, fund, last_limits):
        code = fund["code"]
        limit_val = fund["limit_val"]
        limit_text = fund["limit_text"]

        arrow = ""
        prev = last_limits.get(code)
        if prev is not None:
            if limit_val > prev:
                arrow = " ↑"
            elif limit_val < prev:
                arrow = " ↓"

        limit_display = ""
        markdown_limit_display = ""
        if section_title == "可申购" and limit_text != "None":
            limit_display = f"{limit_text}{arrow}"
            markdown_limit_display = limit_display
        elif section_title == "可申购" and limit_val == float("inf"):
            limit_display = f"不限{arrow}"
            markdown_limit_display = limit_display if arrow else ""
        elif section_title == "不可申购":
            limit_display = fund.get("status") or "暂停"

        return {
            "code": code,
            "name": fund["name"],
            "short_name": self._shorten_name(fund["name"]),
            "status": fund.get("status", ""),
            "limit_text": limit_text,
            "limit_val": limit_val,
            "limit_display": limit_display,
            "markdown_limit_display": markdown_limit_display,
            "arrow": arrow.strip(),
            "available": section_title == "可申购",
        }

    def _build_fee_groups(self, funds_data):
        grouped = {"纳斯达克100": [], "标普500": [], "其他": []}

        for fund in funds_data:
            has_fee_info = any(
                fund.get(key)
                for key in [
                    "operation_display",
                    "subscription_display",
                    "redemption_display",
                    "fee_error",
                ]
            )
            if not has_fee_info:
                continue

            idx_type = self._get_index_type(fund["name"])
            group_name = idx_type if idx_type in grouped else "其他"
            grouped[group_name].append(self._build_report_fee_fund(fund))

        fee_groups = []
        for idx_name in ["纳斯达克100", "标普500", "其他"]:
            funds = grouped[idx_name]
            if funds:
                fee_groups.append({"title": idx_name, "funds": funds})
        return fee_groups

    def _build_report_fee_fund(self, fund):
        return {
            "code": fund["code"],
            "name": fund["name"],
            "short_name": self._shorten_name(fund["name"]),
            "operation_display": fund.get("operation_display", ""),
            "subscription_display": fund.get("subscription_display", ""),
            "redemption_display": fund.get("redemption_display", ""),
            "fee_error": fund.get("fee_error", ""),
        }

    def render_report_markdown(self, report):
        report_lines = ["# " + report["title"], f"> 时间: {report['generated_at']}"]

        for section in report["sections"]:
            report_lines.append(f"## {section['title']}")
            for group in section["groups"]:
                report_lines.append(f"### {group['title']}")
                for fund in group["funds"]:
                    emoji = "🔴" if not fund["available"] else ""
                    line = f"{fund['short_name']}({fund['code']}) {emoji}"

                    if fund["available"] and fund["markdown_limit_display"]:
                        line += f" : {fund['markdown_limit_display']}"

                    report_lines.append(line.strip())

        fee_groups = report.get("fee_groups", [])
        if fee_groups:
            report_lines.append("## 费率摘要")
            for group in fee_groups:
                report_lines.append(f"### {group['title']}")
                report_lines.append("| 基金 | 运作费用 | 申购优惠 | 赎回费率 |")
                report_lines.append("| --- | --- | --- | --- |")
                for fund in group["funds"]:
                    if fund.get("fee_error"):
                        operation = fund["fee_error"]
                        subscription = "--"
                        redemption = "--"
                    else:
                        operation = fund["operation_display"]
                        subscription = fund["subscription_display"]
                        redemption = fund["redemption_display"]
                    report_lines.append(
                        "| "
                        + " | ".join(
                            [
                                self._markdown_table_cell(
                                    f"{fund['short_name']}({fund['code']})"
                                ),
                                self._markdown_table_cell(operation),
                                self._markdown_table_cell(subscription),
                                self._markdown_table_cell(redemption),
                            ]
                        )
                        + " |"
                    )

        return "\n".join(report_lines)

    def _markdown_table_cell(self, value):
        return str(value or "--").replace("|", "\\|").replace("\n", " ")

    def generate_report(self, funds_data):
        report = self.build_report(funds_data)
        return self.render_report_markdown(report)

    def fetch_all_funds(self):
        funds_data = []
        print(f"Fetching data for {len(self.funds_config)} funds...")

        for fund in self.funds_config:
            info = self.fetch_fund_info(fund["code"], fund["name"])
            info.update(self.fetch_fund_fee_info(fund["code"]))
            funds_data.append(info)
            time.sleep(0.5)

        return funds_data

    def prepare_report(self, report_output=None, force_image=False):
        funds_data = self.fetch_all_funds()
        report = self.build_report(funds_data)
        message = self.render_report_markdown(report)
        image_path, image_url = self._prepare_report_image(
            report,
            force_image=force_image,
        )

        payload = {
            "title": report["title"],
            "message": message,
            "image_url": image_url,
        }
        if image_path:
            payload["image_path"] = str(image_path)

        if report_output:
            self._save_json(report_output, payload)

        curr_limits = {f["code"]: f["limit_val"] for f in funds_data}
        self._save_history({"date": time.strftime("%Y-%m-%d"), "limits": curr_limits})
        return payload

    def send_report_payload(self, report_file):
        payload = self._load_json(report_file)
        if not payload:
            raise ValueError(f"Report payload not found or empty: {report_file}")

        return self.notifier.send(
            payload["title"],
            payload["message"],
            image_url=payload.get("image_url"),
        )

    def run(self):
        payload = self.prepare_report(force_image=bool(self._report_image_base_url()))
        self.notifier.send(
            payload["title"],
            payload["message"],
            image_url=payload.get("image_url"),
        )

    def _prepare_report_image(self, report, force_image=False):
        image_base_url = self._report_image_base_url()
        if not force_image and not image_base_url:
            return None, None

        image_dir = Path(os.environ.get("REPORT_IMAGE_DIR", "reports"))
        image_filename = self._report_image_filename(report["generated_at"])
        image_path = image_dir / image_filename
        render_report_image(report, image_path)

        image_url = None
        if image_base_url:
            image_url = f"{image_base_url.rstrip('/')}/{image_filename}"

        return image_path, image_url

    def _report_image_base_url(self):
        return os.environ.get("REPORT_IMAGE_BASE_URL", "").strip()

    def _report_image_filename(self, generated_at):
        timestamp = re.sub(r"[^0-9]", "", generated_at)
        return f"fund-limit-{timestamp}.png"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fund limit monitor")
    parser.add_argument(
        "--prepare-report",
        action="store_true",
        help="Generate report assets and payload without sending notifications.",
    )
    parser.add_argument(
        "--send-report",
        help="Send a prepared report payload JSON file.",
    )
    parser.add_argument(
        "--report-output",
        default=".report/latest.json",
        help="Output path for --prepare-report payload JSON.",
    )
    args = parser.parse_args(argv)

    monitor = FundMonitor()

    if args.send_report:
        success = monitor.send_report_payload(args.send_report)
        raise SystemExit(0 if success else 1)

    if args.prepare_report:
        monitor.prepare_report(report_output=args.report_output, force_image=True)
        return

    monitor.run()


if __name__ == "__main__":
    main()
