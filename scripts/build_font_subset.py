#!/usr/bin/env python3
import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from fontTools import subset


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/main/"
    "Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"
)
DEFAULT_SOURCE_FONT = ROOT_DIR / ".font-build" / "NotoSansCJKsc-Regular.otf"
DEFAULT_OUTPUT_FONT = ROOT_DIR / "assets" / "fonts" / "FundReportSans-Subset.otf"

sys.path.insert(0, str(ROOT_DIR))
from report_renderer import build_font_subset_text  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Build the bundled report font subset.")
    parser.add_argument("--source-font", default=str(DEFAULT_SOURCE_FONT))
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FONT))
    args = parser.parse_args()

    source_font = Path(args.source_font)
    output_font = Path(args.output)
    if not source_font.exists():
        source_font.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading source font to {source_font}")
        urllib.request.urlretrieve(args.source_url, source_font)

    with (ROOT_DIR / "config.json").open("r", encoding="utf-8") as f:
        config = json.load(f)

    subset_text = build_font_subset_text(config)
    output_font.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as text_file:
        text_file.write(subset_text)
        text_file_path = text_file.name

    subset.main(
        [
            str(source_font),
            f"--text-file={text_file_path}",
            f"--output-file={output_font}",
            "--layout-features=*",
            "--glyph-names",
            "--symbol-cmap",
            "--legacy-cmap",
            "--notdef-glyph",
            "--notdef-outline",
            "--name-IDs=*",
            "--name-legacy",
            "--name-languages=*",
        ]
    )
    Path(text_file_path).unlink(missing_ok=True)
    print(f"Wrote {output_font}")


if __name__ == "__main__":
    main()
