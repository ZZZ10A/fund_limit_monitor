import requests
from bs4 import BeautifulSoup
extras = ["501302", "000368", "005699", "006075"]
def check(code):
    url = f"http://fund.eastmoney.com/{code}.html"
    try:
        r = requests.get(url, timeout=5)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        name = soup.select_one(".fundDetail-tit div").get_text(strip=True)
        print(f"{code}: {name}")
    except:
        pass
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor() as e:
    e.map(check, extras)
