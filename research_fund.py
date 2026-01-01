
import requests
from bs4 import BeautifulSoup
import re

def check_fund(code):
    urls = [
        f"http://fund.eastmoney.com/{code.split('.')[0]}.html", # Home
        f"http://fund.eastmoney.com/f10/jbgk_{code.split('.')[0]}.html" # Basic Info
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }

    print(f"Checking Fund: {code}")

    for url in urls:
        print(f"Fetching {url}...")
        try:
            resp = requests.get(url, headers=headers)
            resp.encoding = "utf-8" # Eastmoney uses utf-8 usually, or gb2312
            
            # Simple grep for keywords
            text = resp.text
            keywords = ["申购限额", "单日", "限额", "大额", "暂停申购"]
            
            # Use BS4 to inspect typical locations if possible
            soup = BeautifulSoup(text, 'html.parser')
            
            # Look for "purchase status" related divs
            # Common classes: "fundInfoItem", "staticItem"
            
            print(f"--- Results for {url} ---")
            
            # Method 1: Regex search in full text
            for kw in keywords:
                matches = re.findall(r"([^。！？\n]*" + kw + r"[^。！？\n]*)", text)
                if matches:
                    print(f"Found keyword '{kw}':")
                    for m in matches[:3]:
                        print(f"  - {m.strip()}")

        except Exception as e:
            print(f"Error fetching {url}: {e}")
        print("\n")

if __name__ == "__main__":
    # Test with Guotai Nasdaq 100 (160213) which often has limits
    check_fund("160213")
