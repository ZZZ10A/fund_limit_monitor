import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from notifier import build_notifier
from report_renderer import render_report_image


class FundMonitor:
    CONFIG_FILE = "config.json"
    HISTORY_DB_FILE = "history.db"
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
        self.history_db_path = Path(
            os.environ.get("HISTORY_DB_PATH", self.HISTORY_DB_FILE)
        )
        self._init_history_db()
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

    def _init_history_db(self):
        db_path = getattr(self, "history_db_path", None)
        if not db_path:
            return

        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fund_limit_history (
                    date TEXT PRIMARY KEY,
                    limits_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _load_previous_history_limits(self, report_date):
        db_path = getattr(self, "history_db_path", None)
        if not db_path:
            return {}

        try:
            self._init_history_db()
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT limits_json
                    FROM fund_limit_history
                    WHERE date < ?
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    (report_date,),
                ).fetchone()
        except sqlite3.Error as e:
            print(f"Error loading history database: {e}")
            return {}

        if not row:
            return {}

        try:
            limits = json.loads(row[0])
        except json.JSONDecodeError as e:
            print(f"Error parsing history database record: {e}")
            return {}

        return limits if isinstance(limits, dict) else {}

    def _save_history(self, report_date, funds_data):
        db_path = getattr(self, "history_db_path", None)
        if not db_path:
            return

        limits = self._build_history_limits(funds_data)
        limits_json = json.dumps(limits, ensure_ascii=False, sort_keys=True)
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        self._init_history_db()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO fund_limit_history
                    (date, limits_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    limits_json = excluded.limits_json,
                    updated_at = excluded.updated_at
                """,
                (report_date, limits_json, now, now),
            )

    def _build_history_limits(self, funds_data):
        return {
            str(fund["code"]): self._build_history_entry(fund)
            for fund in funds_data
        }

    def _build_history_entry(self, fund):
        limit_val = fund.get("limit_val")
        limit_value = None
        if limit_val != float("inf"):
            limit_value = limit_val
            if isinstance(limit_value, float) and limit_value.is_integer():
                limit_value = int(limit_value)

        return {
            "code": str(fund.get("code", "")),
            "name": fund.get("name", ""),
            "status": fund.get("status", ""),
            "limit_text": fund.get("limit_text", "None"),
            "limit_value": limit_value,
            "limit_type": self._limit_type_from_fund(fund),
        }

    def _limit_type_from_fund(self, fund):
        status = fund.get("status", "")
        limit_val = fund.get("limit_val")
        if "暂停" in status or limit_val is None or limit_val < 0:
            return "paused"
        if limit_val == float("inf"):
            return "unlimited"
        return "limited"

    def _limit_compare_value(self, history_entry):
        if history_entry is None:
            return None

        if not isinstance(history_entry, dict):
            try:
                value = float(history_entry)
            except (TypeError, ValueError):
                return None
            return -1 if value <= 0 else value

        limit_type = history_entry.get("limit_type")
        if limit_type == "unlimited":
            return float("inf")
        if limit_type == "paused":
            return -1

        value = history_entry.get("limit_value")
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return -1 if value <= 0 else value

    def _history_limit_display(self, history_entry):
        if history_entry is None:
            return ""

        if not isinstance(history_entry, dict):
            return self._format_limit_value(history_entry)

        limit_type = history_entry.get("limit_type")
        limit_text = history_entry.get("limit_text")
        if limit_type == "unlimited":
            return "不限"
        if limit_type == "limited" and limit_text and limit_text != "None":
            return str(limit_text)
        if limit_type == "paused":
            return history_entry.get("status") or "暂停"

        return self._format_limit_value(history_entry.get("limit_value"))

    def _format_limit_value(self, value):
        if value is None:
            return ""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return str(value)

        if amount == float("inf"):
            return "不限"
        if amount < 0:
            return "暂停"
        if amount >= 10000 and amount % 10000 == 0:
            return f"{amount / 10000:g}万元"
        return f"{amount:g}元"

    def _default_limit_display(self, section_title, fund):
        limit_val = fund["limit_val"]
        limit_text = fund["limit_text"]

        if section_title == "可申购" and limit_text != "None":
            return limit_text
        if section_title == "可申购" and limit_val == float("inf"):
            return "不限"
        if section_title == "不可申购":
            return fund.get("status") or "暂停"
        return ""

    def _build_limit_change_fields(self, fund, previous_entry):
        current_entry = self._build_history_entry(fund)
        previous_display = self._history_limit_display(previous_entry)
        current_display = self._history_limit_display(current_entry)
        previous_value = self._limit_compare_value(previous_entry)
        current_value = self._limit_compare_value(current_entry)

        fields = {
            "previous_limit_display": previous_display,
            "current_limit_display": current_display,
            "change_direction": "",
            "change_display": "",
            "arrow": "",
        }

        if (
            previous_value is None
            or current_value is None
            or previous_value == current_value
        ):
            return fields

        if current_value > previous_value:
            fields["change_direction"] = "increase"
            fields["arrow"] = "↑"
        else:
            fields["change_direction"] = "decrease"
            fields["arrow"] = "↓"

        fields["change_display"] = (
            f"{previous_display} -> {current_display} {fields['arrow']}"
        )
        return fields

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
        report_date = generated_at[:10]

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

        last_limits = self._load_previous_history_limits(report_date)
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

        change_fields = self._build_limit_change_fields(
            fund,
            last_limits.get(str(code)),
        )
        default_limit_display = self._default_limit_display(section_title, fund)
        limit_display = change_fields["change_display"] or default_limit_display

        markdown_limit_display = ""
        if section_title == "可申购" and limit_text != "None":
            markdown_limit_display = limit_display
        elif section_title == "可申购" and limit_val == float("inf"):
            markdown_limit_display = (
                limit_display if change_fields["change_display"] else ""
            )
        elif change_fields["change_display"]:
            markdown_limit_display = limit_display

        return {
            "code": code,
            "name": fund["name"],
            "short_name": self._shorten_name(fund["name"]),
            "status": fund.get("status", ""),
            "limit_text": limit_text,
            "limit_val": limit_val,
            "limit_display": limit_display,
            "markdown_limit_display": markdown_limit_display,
            "available": section_title == "可申购",
            **change_fields,
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

                    if fund["markdown_limit_display"]:
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

        self._save_history(report["generated_at"][:10], funds_data)
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
