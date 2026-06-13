import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime
import re
import os
import schedule

class FundMonitor:
    CONFIG_FILE = 'config.json'
    
    def __init__(self):
        self.load_config()
        
    def load_config(self):
        """每次运行时重新加载配置，支持热更新"""
        if not os.path.exists(self.CONFIG_FILE):
            print(f"配置文件 {self.CONFIG_FILE} 不存在！")
            self.config = {}
        else:
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except Exception as e:
                print(f"解析 {self.CONFIG_FILE} 失败: {e}")
                self.config = {}
                
        self.webhook_url = os.environ.get('WEBHOOK_URL') or self.config.get('webhook_url')
        self.funds_config = self.config.get('funds', [])

    def _parse_amount(self, text):
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

    def _get_company_name(self, name):
        """提取基金公司名称，剥离指数名和冗余后缀"""
        remove_words = [
            "纳斯达克100", "纳斯达克", "标普500", "纳指100", "纳指", 
            "ETF联接", "指数", "发起式", "发起", "精选", "股票", "(LOF)", "A", "C"
        ]
        for w in remove_words:
            name = name.replace(w, "")
        return name.strip()

    def _get_index_type(self, name):
        if "纳斯达克" in name or "纳指" in name:
            return "纳斯达克100"
        if "标普" in name:
            return "标普500"
        return "其他"

    def fetch_fund_info(self, code, name):
        url = f"http://fund.eastmoney.com/f10/jbgk_{code}.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
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
            
            status_match = re.search(r"交易状态：\s*(\S+)", full_text)
            if status_match:
                info['status'] = status_match.group(1)
            else:
                th = soup.find(lambda tag: tag.name in ['th', 'td'] and '交易状态' in tag.get_text())
                if th and th.find_next_sibling('td'):
                    info['status'] = th.find_next_sibling('td').get_text(strip=True)

            limit_match = re.search(r"（(.*单日.*上限.*)）", resp.text)
            if limit_match:
                 raw_limit = limit_match.group(1)
                 clean_limit = re.sub(r'<[^>]+>', '', raw_limit)
                 info['limit_text'] = re.sub(r"单日.*?上限", "", clean_limit).replace("（", "").replace("）", "")
            
            if "暂停" in info['status']:
                info['limit_val'] = -1
            elif info['limit_text'] != "None":
                info['limit_val'] = self._parse_amount(info['limit_text'])
            else:
                info['limit_val'] = float('inf')

        except Exception as e:
            print(f"抓取 {code} 失败: {e}")
            
        return info

    def send_notification(self, message):
        if not self.webhook_url or "YOUR_KEY" in self.webhook_url:
            print("Webhook 未配置，打印到控制台：\n")
            print(message)
            return

        headers = {'Content-Type': 'application/json'}
        data = {
            "msgtype": "markdown",
            "markdown": {"content": message}
        }
        
        try:
            resp = requests.post(self.webhook_url, json=data, headers=headers)
            print(f"推送完成. 状态码: {resp.status_code}")
        except Exception as e:
            print(f"推送失败: {e}")

    def generate_report(self, funds_data):
        funds_data.sort(key=lambda x: x['limit_val'], reverse=True)
        
        groups = {
            "可申购": {"纳斯达克100": [], "标普500": [], "其他": []},
            "不可申购": {"纳斯达克100": [], "标普500": [], "其他": []}
        }

        for info in funds_data:
            is_paused = "暂停" in info['status']
            category = "不可申购" if (is_paused or info['limit_val'] == 0) else "可申购"
            
            idx_type = self._get_index_type(info['name'])
            groups[category][idx_type].append(info)

        report_lines = [
            "# 📊 QDII 基金申购限额播报", 
            f"> **更新时间**: <font color='comment'>{datetime.now().strftime('%Y-%m-%d %H:%M')}</font>\n"
        ]

        def add_section(title, emoji, grouped_funds):
            total_count = sum(len(v) for v in grouped_funds.values())
            if total_count == 0:
                return

            report_lines.append(f"## {emoji} {title}")
            
            for idx_name in ["纳斯达克100", "标普500", "其他"]:
                funds = grouped_funds.get(idx_name, [])
                if not funds:
                    continue
                
                report_lines.append(f"**【{idx_name}】**")
                
                for f in funds:
                    company = self._get_company_name(f['name'])
                    code = f['code']
                    limit_text = f['limit_text']
                    limit_val = f['limit_val']
                    target_val = f['target_amount']
                    
                    # 按照极简格式拼接：公司名 + 代码 ｜
                    line = f"- {company}{code} ｜ "
                    
                    if title == "可申购":
                        if limit_text != "None":
                            line += f"**{limit_text}**"
                            # 单个基金额度对比
                            if target_val > 0 and 0 < limit_val < target_val:
                                line += " ⚠️" 
                        else:
                            line += "**不限**"
                    else:
                        line += "<font color='warning'>暂停申购</font>"
                    
                    report_lines.append(line)
                report_lines.append("") 

        add_section("可申购", "✅", groups["可申购"])
        add_section("不可申购", "❌", groups["不可申购"])
        
        return "\n".join(report_lines)

    def run(self):
        self.load_config() 
        funds_data = []
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始抓取 {len(self.funds_config)} 支基金数据...")
        
        for fund in self.funds_config:
            target = fund.get('target_amount', 0)
            info = self.fetch_fund_info(fund['code'], fund['name'])
            info['target_amount'] = target
            funds_data.append(info)
            time.sleep(0.5) 
            
        message = self.generate_report(funds_data)
        self.send_notification(message)


def job():
    """定义调度任务"""
    if datetime.now().weekday() <= 4:
        monitor.run()
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 周末，跳过抓取任务。")


if __name__ == "__main__":
    monitor = FundMonitor()
    
    # 设定每天定时执行的时间（注意时区）
    schedule.every().day.at("14:00").do(job)
    
    print("监控服务已启动，正在执行首次测试抓取以确认配置...")
    # 首次启动时立刻运行一次，方便检查结果
    monitor.run() 
    print("\n首次测试完成。程序已挂起，等待下一个定时执行时间...")
    
    # 保持进程一直运行
    while True:
        schedule.run_pending()
        time.sleep(30)