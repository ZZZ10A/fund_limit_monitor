import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "FundReportSans-Subset.otf"

REPORT_STATIC_TEXT = (
    "基金申购限额日报A类时间可申购不可申购纳斯达克100标普500其他"
    "不限暂停开放申购赎回定投转换转入转出交易状态限额单日累计购买"
    "上限金额人民币元万元千万亿元大额恢复关闭封闭认购未知"
    "费率摘要名称价差信息运作费率运作费用管理托管销售服务优惠银行卡活期宝合计每年"
    "持有天年月日以上以内不足满获取失败小于大于等于"
    "华夏博时华安嘉实建信大成招商华宝华泰天弘摩根南方易方达"
    "广发国泰精选股票发起式指数联接ETFLOF"
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "（）()[]【】<>《》:：；,，.。/ -_#%+*="
    "↑↓"
)

INDEX_TABLE_TITLES = ("纳斯达克100", "标普500")
TABLE_HEADERS = ("名称", "价差信息", "运作费率", "申购优惠", "赎回费率")


def build_font_subset_text(config):
    parts = [REPORT_STATIC_TEXT]
    for fund in config.get("funds", []):
        parts.append(str(fund.get("code", "")))
        parts.append(str(fund.get("name", "")))
    return "".join(parts)


def get_report_font_path():
    configured = os.environ.get("REPORT_FONT_PATH")
    if configured:
        return Path(configured)
    return DEFAULT_FONT_PATH


def render_report_image(report, output_path, font_path=None):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    font_path = Path(font_path) if font_path else get_report_font_path()
    if not font_path.exists():
        raise FileNotFoundError(f"Report font not found: {font_path}")

    fonts = {
        "title": _load_font(font_path, 40),
        "meta": _load_font(font_path, 20),
        "table_title": _load_font(font_path, 28),
        "summary": _load_font(font_path, 18),
        "header": _load_font(font_path, 18),
        "cell": _load_font(font_path, 17),
    }

    width = 1400
    padding = 44
    content_width = width - padding * 2
    tables = _build_index_tables(report)
    measure_draw = ImageDraw.Draw(Image.new("RGB", (width, 1), "#ffffff"))
    height = _measure_height(tables, measure_draw, fonts, padding, content_width)

    image = Image.new("RGB", (width, height), "#f7f9fc")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        [padding - 12, padding - 10, width - padding + 12, height - padding + 10],
        radius=20,
        fill="#ffffff",
        outline="#e4e9f0",
        width=1,
    )

    y = padding + 16
    draw.text(
        (padding + 12, y),
        report["title"],
        fill="#172033",
        font=fonts["title"],
    )
    y += 54
    draw.text(
        (padding + 14, y),
        f"时间: {report['generated_at']}",
        fill="#6b7280",
        font=fonts["meta"],
    )
    y += 46

    for table in tables:
        y = _draw_index_table(
            draw,
            fonts,
            table,
            padding + 12,
            y,
            content_width - 24,
        )
        y += 30

    image.save(output_path, "PNG")
    return output_path


def _load_font(font_path, size):
    return ImageFont.truetype(str(font_path), size=size)


def _build_index_tables(report):
    fee_by_code = {}
    for group in report.get("fee_groups", []):
        for fund in group.get("funds", []):
            code = str(fund.get("code", ""))
            if code:
                fee_by_code[code] = fund

    grouped = {
        title: {"可申购": [], "不可申购": []}
        for title in INDEX_TABLE_TITLES
    }
    for section in report.get("sections", []):
        availability = section.get("title", "")
        if availability not in ("可申购", "不可申购"):
            continue

        for group in section.get("groups", []):
            index_title = _normalize_index_title(group.get("title", ""))
            if not index_title:
                continue

            for fund in group.get("funds", []):
                code = str(fund.get("code", ""))
                grouped[index_title][availability].append(
                    _build_table_row(
                        fund,
                        availability,
                        fee_by_code.get(code, {}),
                    )
                )

    tables = []
    for title in INDEX_TABLE_TITLES:
        available_rows = grouped[title]["可申购"]
        unavailable_rows = grouped[title]["不可申购"]
        rows = available_rows + unavailable_rows
        if not rows:
            continue

        tables.append(
            {
                "title": title,
                "summary": (
                    f"可申购: {len(available_rows)} / "
                    f"不可申购: {len(unavailable_rows)}"
                ),
                "rows": rows,
            }
        )
    return tables


def _normalize_index_title(title):
    title = str(title or "")
    if "纳斯达克" in title or "纳指" in title:
        return "纳斯达克100"
    if "标普" in title:
        return "标普500"
    return ""


def _build_table_row(fund, availability, fee):
    code = str(fund.get("code", ""))
    fee_error = fee.get("fee_error") or fund.get("fee_error", "")

    if fee_error:
        operation = fee_error
        subscription = "--"
        redemption = "--"
    else:
        operation = (
            fee.get("operation_display")
            or fund.get("operation_display")
            or "--"
        )
        subscription = (
            fee.get("subscription_display")
            or fund.get("subscription_display")
            or "--"
        )
        redemption = (
            fee.get("redemption_display")
            or fund.get("redemption_display")
            or "--"
        )

    return {
        "name": f"{fund.get('name') or fund.get('short_name') or ''}({code})",
        "spread": _spread_display(fund, availability),
        "operation": _operation_fee_display(operation),
        "subscription": _subscription_fee_display(subscription),
        "redemption": _redemption_fee_display(redemption),
        "availability": availability,
        "change_direction": fund.get("change_direction", ""),
        "fee_error": bool(fee_error),
    }


def _spread_display(fund, availability):
    detail = fund.get("limit_display") or fund.get("status") or ""
    if not detail or detail == "None":
        detail = "不限" if availability == "可申购" else "暂停"
    if detail == availability:
        return availability
    return f"{availability}\n{detail}"


def _operation_fee_display(value):
    value = str(value or "--").strip()
    if value in ("", "--"):
        return "--"
    value = re.sub(r"\s+", " ", value)
    labels = ("托管", "销售", "合计")
    if any(f" {label}" in value for label in labels):
        value = re.sub(r"\s+(?=(?:托管|销售|合计))", "\n", value).strip()
    else:
        value = re.sub(r"(?<!^)(?=(?:托管|销售|合计))", "\n", value).strip()

    items = [item.strip() for item in value.splitlines() if item.strip()]
    return "\n".join(
        " ".join(items[index : index + 2])
        for index in range(0, len(items), 2)
    )


def _subscription_fee_display(value):
    value = str(value or "--").strip()
    if value in ("", "--"):
        return "--"
    value = re.sub(r"\s+", " ", value)
    parts = value.split(" ", 1)
    if len(parts) == 2:
        return f"{parts[0]}\n{parts[1]}"
    return value


def _redemption_fee_display(value):
    value = str(value or "--").strip()
    if value in ("", "--"):
        return "--"
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"\s*/\s*", "\n", value)


def _measure_height(tables, draw, fonts, padding, content_width):
    height = padding * 2 + 126
    table_width = content_width - 24
    for table in tables:
        height += 44
        height += 40
        for row in table["rows"]:
            height += _measure_table_row(draw, fonts, row, table_width)
        height += 30
    return max(height, 360)


def _draw_index_table(draw, fonts, table, x, y, table_width):
    draw.text((x, y), table["title"], fill="#172033", font=fonts["table_title"])
    summary_width = _text_width(draw, table["summary"], fonts["summary"])
    draw.text(
        (x + table_width - summary_width, y + 8),
        table["summary"],
        fill="#64748b",
        font=fonts["summary"],
    )
    y += 44
    y = _draw_table_header(draw, fonts, x, y, table_width)

    for index, row in enumerate(table["rows"]):
        row_height = _measure_table_row(draw, fonts, row, table_width)
        y = _draw_table_row(
            draw,
            fonts,
            row,
            x,
            y,
            table_width,
            row_height,
            index,
        )
    return y


def _draw_table_header(draw, fonts, x, y, table_width):
    row_height = 40
    columns = _table_columns(table_width)
    draw.rounded_rectangle(
        [x, y, x + table_width, y + row_height],
        radius=10,
        fill="#eff6ff",
        outline="#dbeafe",
        width=1,
    )

    offset = x
    for i, (label, width) in enumerate(zip(TABLE_HEADERS, columns)):
        if i > 0:
            draw.line([offset, y, offset, y + row_height], fill="#dbeafe", width=1)
        draw.text((offset + 10, y + 9), label, fill="#1d4ed8", font=fonts["header"])
        offset += width

    return y + row_height


def _draw_table_row(draw, fonts, row, x, y, table_width, row_height, index):
    columns = _table_columns(table_width)
    fill = "#ffffff" if index % 2 == 0 else "#f8fafc"
    draw.rectangle(
        [x, y, x + table_width, y + row_height],
        fill=fill,
        outline="#eef2f7",
        width=1,
    )

    stripe_fill = "#16a34a" if row["availability"] == "可申购" else "#dc2626"
    draw.rectangle([x, y, x + 5, y + row_height], fill=stripe_fill)

    offset = x
    for i, (value, width) in enumerate(zip(_table_values(row), columns)):
        if i > 0:
            draw.line([offset, y, offset, y + row_height], fill="#eef2f7", width=1)
        _draw_wrapped_cell(
            draw,
            str(value),
            fonts["cell"],
            offset + 8,
            y + 10,
            width - 16,
            _table_cell_fill(row, i),
            line_height=22,
        )
        offset += width

    return y + row_height


def _measure_table_row(draw, fonts, row, table_width):
    columns = _table_columns(table_width)
    max_lines = 1
    for value, width in zip(_table_values(row), columns):
        max_lines = max(
            max_lines,
            len(_wrap_text(draw, value, fonts["cell"], width - 16)),
        )
    return max(58, max_lines * 22 + 20)


def _table_columns(table_width):
    name_width = 260
    spread_width = 190
    operation_width = 330
    subscription_width = 180
    redemption_width = table_width - (
        name_width + spread_width + operation_width + subscription_width
    )
    return [
        name_width,
        spread_width,
        operation_width,
        subscription_width,
        redemption_width,
    ]


def _table_values(row):
    return [
        row["name"],
        row["spread"],
        row["operation"],
        row["subscription"],
        row["redemption"],
    ]


def _table_cell_fill(row, index):
    if index == 1:
        if row["change_direction"] == "increase":
            return "#15803d"
        if row["change_direction"] == "decrease":
            return "#b91c1c"
        return "#15803d" if row["availability"] == "可申购" else "#b91c1c"
    if index == 2 and row["fee_error"]:
        return "#b91c1c"
    return "#111827" if index == 0 else "#475569"


def _draw_wrapped_cell(draw, text, font, x, y, max_width, fill, line_height):
    lines = _wrap_text(draw, text, font, max_width)
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_height), line, fill=fill, font=font)


def _wrap_text(draw, text, font, max_width):
    text = str(text or "")
    lines = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        lines.extend(_wrap_paragraph(draw, paragraph, font, max_width))
    return lines or [""]


def _wrap_paragraph(draw, paragraph, font, max_width):
    tokens = paragraph.split(" ")
    if len(tokens) == 1:
        return _wrap_long_token(draw, paragraph, font, max_width)

    lines = []
    current = ""
    for token in tokens:
        if token == "":
            continue

        candidate = token if not current else f"{current} {token}"
        if not current:
            current = token
            continue
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue

        lines.extend(_wrap_long_token(draw, current, font, max_width))
        current = token

    if current:
        lines.extend(_wrap_long_token(draw, current, font, max_width))
    return lines or [""]


def _wrap_long_token(draw, token, font, max_width):
    lines = []
    current = ""
    for char in token:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current = candidate

    if current:
        lines.append(current.rstrip())
    return lines or [""]


def _text_width(draw, text, font):
    return draw.textlength(str(text), font=font)
