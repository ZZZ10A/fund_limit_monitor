import requests
from bs4 import BeautifulSoup

candidates = [
    # NDX
    "160213", "270042", "015299", "016055", "040046", "016532", "539001", "000834", 
    "019547", "014201", "016919", "017894",
    # SPX
    "161125", "050025", "007721", "003718", "018034", "018064", "018134", "019283", "019349"
]

def check(code):
    url = f"http://fund.eastmoney.com/{code}.html"
    try:
        r = requests.get(url, timeout=5)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        name_tag = soup.select_one(".fundDetail-tit div")
        if name_tag:
            name = name_tag.get_text(strip=True)
            # Check if A or C
            # We want A. Usually if name doesn't say C, it is A, or mixed.
            # But if it specifically says C, we skip.
            print(f"{code}: {name}")
        else:
            print(f"{code}: Name Not Found")
    except Exception as e:
        print(f"{code}: Error {e}")

from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=5) as executor:
    executor.map(check, candidates)
