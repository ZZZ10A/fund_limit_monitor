import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os

from notifier import build_notifier

class FundMonitor:
    CONFIG_FILE = 'config.json'
    HISTORY_FILE = 'history.json'
    
    def __init__(self):
        self.config = self._load_json(self.CONFIG_FILE)
        self.history = self._load_json(self.HISTORY_FILE)
        self.notifier = build_notifier(self.config)
        self.funds_config = self.config.get('funds', [])
        
    def _load_json(self, filename):
        if not os.path.exists(filename):
            return {}
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return {}

    def _save_history(self, data):
        with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
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
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
        }
        
        info = {
            "code": code,
            "name": name,
            "status": "Unknown",
            "limit_text": "None",
            "limit_val": -1 
        }

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            full_text = soup.get_text()
            
            # 1. Status
            status_match = re.search(r"交易状态：\s*(\S+)", full_text)
            if status_match:
                info['status'] = status_match.group(1)
            else:
                th = soup.find(lambda tag: tag.name in ['th', 'td'] and '交易状态' in tag.get_text())
                if th and th.find_next_sibling('td'):
                    info['status'] = th.find_next_sibling('td').get_text(strip=True)

            # 2. Limit Text
            limit_match = re.search(r"（(.*单日.*上限.*)）", resp.text)
            if limit_match:
                 raw_limit = limit_match.group(1)
                 clean_limit = re.sub(r'<[^>]+>', '', raw_limit)
                 info['limit_text'] = re.sub(r"单日.*?上限", "", clean_limit).replace("（", "").replace("）", "")
            
            # 3. Numeric Value
            if "暂停" in info['status']:
                info['limit_val'] = -1
            elif info['limit_text'] != "None":
                info['limit_val'] = self._parse_amount(info['limit_text'])
            else:
                info['limit_val'] = float('inf')

        except Exception as e:
            print(f"Error fetching {code}: {e}")
            
        return info

    def generate_report(self, funds_data):
        # Sort by limit value descending
        funds_data.sort(key=lambda x: x['limit_val'], reverse=True)
        
        # Categorize
        groups = {
            "可申购": {"纳斯达克100": [], "标普500": [], "其他": []},
            "不可申购": {"纳斯达克100": [], "标普500": [], "其他": []}
        }

        for info in funds_data:
            is_paused = "暂停" in info['status']
            category = "不可申购" if (is_paused or info['limit_val'] == 0) else "可申购"
            
            idx_type = self._get_index_type(info['name'])
            if idx_type not in groups[category]:
                groups[category]["其他"] = groups[category].get("其他", [])
                groups[category]["其他"].append(info)
            else:
                groups[category][idx_type].append(info)

        # Build Message
        report_lines = ["# 基金申购限额日报 (A类)", f"> 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        
        last_limits = self.history.get('limits', {})

        def add_section(title, grouped_funds):
            total_count = sum(len(v) for v in grouped_funds.values())
            if total_count == 0:
                return

            report_lines.append(f"## {title}")
            
            for idx_name in ["纳斯达克100", "标普500", "其他"]:
                funds = grouped_funds.get(idx_name, [])
                if not funds:
                    continue
                
                report_lines.append(f"### {idx_name}")
                
                for f in funds:
                    s_name = self._shorten_name(f['name'])
                    code = f['code']
                    limit_text = f['limit_text']
                    limit_val = f['limit_val']
                    
                    # Emoji
                    emoji = "🔴" if title == "不可申购" else ""
                    
                    # Comparison Arrow
                    arrow = ""
                    prev = last_limits.get(code)
                    if prev is not None:
                        if limit_val > prev: arrow = " ↑"
                        elif limit_val < prev: arrow = " ↓"

                    line = f"{s_name}({code}) {emoji}"
                    
                    if title == "可申购" and limit_text != "None":
                        line += f" : {limit_text}{arrow}"
                    elif title == "可申购" and limit_val == float('inf') and arrow:
                        line += f" : 不限{arrow}"
                    
                    report_lines.append(line.strip())

        add_section("可申购", groups["可申购"])
        add_section("不可申购", groups["不可申购"])
        
        return "\n".join(report_lines)

    def run(self):
        funds_data = []
        print(f"Fetching data for {len(self.funds_config)} funds...")
        
        for fund in self.funds_config:
            info = self.fetch_fund_info(fund['code'], fund['name'])
            funds_data.append(info)
            time.sleep(0.5)
            
        message = self.generate_report(funds_data)
        self.notifier.send("基金申购限额日报", message)
        
        # Save History
        curr_limits = {f['code']: f['limit_val'] for f in funds_data}
        self._save_history({"date": time.strftime('%Y-%m-%d'), "limits": curr_limits})

if __name__ == "__main__":
    monitor = FundMonitor()
    monitor.run()
