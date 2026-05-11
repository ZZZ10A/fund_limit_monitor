import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "FundReportSans-Subset.otf"

REPORT_STATIC_TEXT = (
    "基金申购限额日报A类时间可申购不可申购纳斯达克100标普500其他"
    "不限暂停开放申购赎回定投转换转入转出交易状态限额单日累计购买"
    "上限金额人民币元万元千万亿元大额恢复关闭封闭认购未知"
    "费率摘要运作费用管理托管销售服务优惠银行卡活期宝合计每年"
    "持有天获取失败小于大于等于"
    "华夏博时华安嘉实建信大成招商华宝华泰天弘摩根南方易方达"
    "广发国泰精选股票发起式指数联接ETFLOF"
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "（）()[]【】<>《》:：；,，.。/ -_#%+*="
    "↑↓"
)


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
        "section": _load_font(font_path, 28),
        "group": _load_font(font_path, 22),
        "name": _load_font(font_path, 24),
        "code": _load_font(font_path, 18),
        "limit": _load_font(font_path, 22),
        "small": _load_font(font_path, 18),
    }

    width = 960
    padding = 44
    content_width = width - padding * 2
    rows = _flatten_report_rows(report)
    height = _measure_height(rows, padding)

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
    draw.text((padding + 12, y), report["title"], fill="#172033", font=fonts["title"])
    y += 54
    draw.text(
        (padding + 14, y),
        f"时间: {report['generated_at']}",
        fill="#6b7280",
        font=fonts["meta"],
    )
    y += 46

    for row in rows:
        kind = row["kind"]
        if kind == "section":
            _draw_section_pill(draw, fonts, row["title"], padding + 12, y)
            y += 56
        elif kind == "group":
            draw.text((padding + 14, y), row["title"], fill="#334155", font=fonts["group"])
            y += 36
        elif kind == "fund":
            y = _draw_fund_row(draw, fonts, row["fund"], padding + 14, y, content_width)
            y += 10
        elif kind == "fee_section":
            _draw_section_pill(draw, fonts, row["title"], padding + 12, y)
            y += 56
        elif kind == "fee_group":
            draw.text((padding + 14, y), row["title"], fill="#334155", font=fonts["group"])
            y += 34
        elif kind == "fee_header":
            y = _draw_fee_table_header(draw, fonts, padding + 14, y, content_width)
        elif kind == "fee_fund":
            y = _draw_fee_fund_row(
                draw,
                fonts,
                row["fund"],
                padding + 14,
                y,
                content_width,
            )

    image.save(output_path, "PNG")
    return output_path


def _load_font(font_path, size):
    return ImageFont.truetype(str(font_path), size=size)


def _flatten_report_rows(report):
    rows = []
    for section in report.get("sections", []):
        rows.append({"kind": "section", "title": section["title"]})
        for group in section.get("groups", []):
            rows.append({"kind": "group", "title": group["title"]})
            for fund in group.get("funds", []):
                rows.append({"kind": "fund", "fund": fund})
    fee_groups = report.get("fee_groups", [])
    if fee_groups:
        rows.append({"kind": "fee_section", "title": "费率摘要"})
        for group in fee_groups:
            rows.append({"kind": "fee_group", "title": group["title"]})
            rows.append({"kind": "fee_header"})
            for fund in group.get("funds", []):
                rows.append({"kind": "fee_fund", "fund": fund})
    return rows


def _measure_height(rows, padding):
    height = padding * 2 + 126
    for row in rows:
        if row["kind"] == "section":
            height += 56
        elif row["kind"] == "group":
            height += 36
        elif row["kind"] == "fund":
            height += 62
        elif row["kind"] == "fee_section":
            height += 56
        elif row["kind"] == "fee_group":
            height += 34
        elif row["kind"] == "fee_header":
            height += 34
        elif row["kind"] == "fee_fund":
            height += 66
    return max(height, 360)


def _draw_section_pill(draw, fonts, title, x, y):
    colors = {
        "可申购": "#15803d",
        "不可申购": "#b91c1c",
        "费率摘要": "#2563eb",
    }
    color = colors.get(title, "#334155")
    pill_height = 38
    pill_width = {
        "可申购": 126,
        "不可申购": 150,
        "费率摘要": 150,
    }.get(title, 150)
    draw.rounded_rectangle(
        [x, y, x + pill_width, y + pill_height],
        radius=19,
        fill=color,
    )
    _draw_centered_text(
        draw,
        title,
        [x, y, x + pill_width, y + pill_height],
        fonts["section"],
        "#ffffff",
    )


def _draw_fund_row(draw, fonts, fund, x, y, content_width):
    row_height = 52
    draw.rounded_rectangle(
        [x, y, x + content_width - 24, y + row_height],
        radius=12,
        fill="#f8fafc",
        outline="#eef2f7",
        width=1,
    )

    available = fund.get("available", False)
    dot_color = "#16a34a" if available else "#dc2626"
    draw.ellipse([x + 16, y + 19, x + 30, y + 33], fill=dot_color)

    name = fund.get("short_name") or fund.get("name") or ""
    code = str(fund.get("code", ""))
    limit = fund.get("limit_display") or fund.get("status") or ""

    left_x = x + 44
    right_x = x + content_width - 42
    limit_width = _text_width(draw, limit, fonts["limit"])
    max_name_width = max(220, right_x - left_x - limit_width - 36)
    display_name = _truncate_text(draw, name, fonts["name"], max_name_width)

    draw.text((left_x, y + 11), display_name, fill="#111827", font=fonts["name"])
    code_x = left_x + _text_width(draw, display_name, fonts["name"]) + 10
    if code_x < right_x - limit_width - 30:
        draw.text((code_x, y + 18), f"({code})", fill="#64748b", font=fonts["code"])

    draw.text((right_x - limit_width, y + 14), limit, fill="#111827", font=fonts["limit"])
    return y + row_height


def _draw_fee_table_header(draw, fonts, x, y, content_width):
    row_height = 34
    row_width = content_width - 24
    columns = _fee_table_columns(row_width)
    draw.rounded_rectangle(
        [x, y, x + row_width, y + row_height],
        radius=10,
        fill="#eff6ff",
        outline="#dbeafe",
        width=1,
    )

    labels = ["基金", "运作费用", "申购优惠", "赎回费率"]
    offset = x
    for i, (label, width) in enumerate(zip(labels, columns)):
        if i > 0:
            draw.line([offset, y, offset, y + row_height], fill="#dbeafe", width=1)
        draw.text((offset + 10, y + 7), label, fill="#1d4ed8", font=fonts["small"])
        offset += width

    return y + row_height


def _draw_fee_fund_row(draw, fonts, fund, x, y, content_width):
    row_height = 66
    row_width = content_width - 24
    columns = _fee_table_columns(row_width)
    draw.rectangle(
        [x, y, x + row_width, y + row_height],
        fill="#f8fafc",
        outline="#eef2f7",
        width=1,
    )

    values = [
        f"{fund.get('short_name') or fund.get('name') or ''}({fund.get('code', '')})",
        fund.get("operation_display") or "--",
        fund.get("subscription_display") or "--",
        fund.get("redemption_display") or "--",
    ]

    fills = ["#111827", "#475569", "#475569", "#475569"]

    if fund.get("fee_error"):
        values = [values[0], fund["fee_error"], "--", "--"]
        fills = ["#111827", "#b91c1c", "#475569", "#475569"]

    offset = x
    for i, (value, width) in enumerate(zip(values, columns)):
        if i > 0:
            draw.line([offset, y, offset, y + row_height], fill="#eef2f7", width=1)
        _draw_wrapped_cell(
            draw,
            str(value),
            fonts["small"],
            offset + 8,
            y + 10,
            width - 16,
            fills[i],
            max_lines=2,
            line_height=21,
        )
        offset += width

    return y + row_height


def _fee_table_columns(row_width):
    fund_width = 182
    subscription_width = 138
    redemption_width = 220
    operation_width = row_width - fund_width - subscription_width - redemption_width
    return [fund_width, operation_width, subscription_width, redemption_width]


def _draw_wrapped_cell(draw, text, font, x, y, max_width, fill, max_lines, line_height):
    lines = _wrap_text(draw, text, font, max_width, max_lines)
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_height), line, fill=fill, font=font)


def _wrap_text(draw, text, font, max_width, max_lines):
    text = str(text or "")
    if _text_width(draw, text, font) <= max_width:
        return [text]

    tokens = text.split(" ")
    lines = []
    current = ""

    for token in tokens:
        candidate = token if not current else f"{current} {token}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = token
        else:
            current = token

        if len(lines) == max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if lines:
        lines[-1] = _truncate_text(draw, lines[-1], font, max_width)
    return lines or [_truncate_text(draw, text, font, max_width)]


def _truncate_text(draw, text, font, max_width):
    if _text_width(draw, text, font) <= max_width:
        return text

    ellipsis = "..."
    available = max_width - _text_width(draw, ellipsis, font)
    truncated = ""
    for char in text:
        if _text_width(draw, truncated + char, font) > available:
            break
        truncated += char
    return truncated + ellipsis


def _text_width(draw, text, font):
    return draw.textlength(str(text), font=font)


def _draw_centered_text(draw, text, box, font, fill):
    text = str(text)
    left, top, right, bottom = box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = left + ((right - left) - text_width) / 2 - bbox[0]
    y = top + ((bottom - top) - text_height) / 2 - bbox[1]
    draw.text((x, y), text, fill=fill, font=font)
