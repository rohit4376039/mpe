import os, re, json, time, threading, csv, io
from pathlib import Path

import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_URL   = "https://mpe.motorolasolutions.com/"
STATE_FILE = "/tmp/mpe_state.json"
LOG_FILE   = "/tmp/mpe_log.txt"
LOCK       = threading.Lock()
CSV_FIELDS = ["company_name","website","email","program_level","community","region","address","phone"]

ALL_REGIONS = [
    "United States","Canada","Mexico","Brazil","Argentina","Colombia","Chile",
    "United Kingdom","Germany","France","Italy","Spain","Netherlands","Belgium",
    "Sweden","Norway","Denmark","Finland","Poland","Czech Republic","Austria","Switzerland",
    "Australia","New Zealand","India","Japan","South Korea","Singapore","Malaysia",
    "South Africa","UAE","Saudi Arabia","Israel","Turkey"
]

# ─── STATE HELPERS ───────────────────────────────────────────────────────────
def write_state(state):
    with LOCK:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)

def reset_state():
    write_state({"running": False, "done": False, "results": []})
    try: os.remove(LOG_FILE)
    except: pass

def append_log(msg):
    with LOCK:
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")

def read_logs():
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f: return f.read()
    except: pass
    return ""

def append_result(row):
    with LOCK:
        state = read_state()
        state["results"].append(row)
        write_state(state)

def read_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f: return json.load(f)
    except: pass
    return {"running": False, "done": False, "results": []}

# ─── DRIVER ──────────────────────────────────────────────────────────────────
def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36")

    for path in ["/usr/bin/chromium","/usr/bin/chromium-browser","/usr/bin/google-chrome"]:
        if os.path.exists(path):
            opts.binary_location = path
            break

    service = None
    for dp in ["/usr/bin/chromedriver","/usr/lib/chromium/chromedriver","/usr/lib/chromium-browser/chromedriver"]:
        if os.path.exists(dp):
            service = Service(dp)
            break

    return webdriver.Chrome(service=service, options=opts) if service else webdriver.Chrome(options=opts)

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def extract_email(text):
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text or "")
    return m.group(0) if m else ""

def extract_phone(text):
    m = re.search(r"(\+?\d[\d\s\-().]{7,})", text or "")
    return m.group(1).strip() if m else ""

def wait_for_results(driver, timeout=15):
    """Wait until the page has loaded some partner result content."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR,
                "[class*='partner'],[class*='result'],[class*='card'],[class*='dealer'],[class*='reseller'],article,li.item")) > 0
        )
        return True
    except:
        return False

def scroll_page(driver, scroll_pause):
    last_h = 0
    for _ in range(6):
        driver.execute_script("window.scrollTo(0,document.body.scrollHeight);")
        time.sleep(scroll_pause)
        new_h = driver.execute_script("return document.body.scrollHeight")
        if new_h == last_h:
            break
        last_h = new_h
    driver.execute_script("window.scrollTo(0,0);")

def find_cards(driver):
    """Try progressively broader selectors to find partner cards."""
    selectors = [
        "[class*='partner-card']",
        "[class*='PartnerCard']",
        "[class*='partner_card']",
        "[class*='result-card']",
        "[class*='resultCard']",
        "[class*='dealer-card']",
        "[class*='partnerResult']",
        "[class*='partner-item']",
        "[class*='locator-result']",
        "div[class*='card'][class*='partner']",
        "article",
        "li[class*='result']",
        "li[class*='partner']",
        ".search-results > div",
        "[data-component*='partner']",
        "[data-testid*='partner']",
        "[data-testid*='result']",
    ]
    for sel in selectors:
        cards = driver.find_elements(By.CSS_SELECTOR, sel)
        if len(cards) > 0:
            return cards, sel
    return [], None

def parse_card(card, driver):
    """Extract data from a partner card element."""
    try:
        text = card.text.strip()
        if not text or len(text) < 5:
            return None

        row = {f: "" for f in CSV_FIELDS}
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return None

        row["company_name"] = lines[0]

        # Look for program level keywords
        for line in lines:
            ll = line.lower()
            for lvl in ["platinum","gold","silver","bronze","authorized","premier","elite","select"]:
                if lvl in ll:
                    row["program_level"] = line
                    break

        # Community / category
        for line in lines:
            ll = line.lower()
            for cat in ["video","radio","software","security","command","critical","broadband","mototrbo","radio","two-way"]:
                if cat in ll and line != row["program_level"]:
                    row["community"] = line
                    break

        # Address lines (after company name)
        addr_lines = []
        for line in lines[1:]:
            if re.search(r'\d{4,}|\b[A-Z]{2}\b|\bstreet\b|\bave\b|\brd\b|\bblvd\b|\bsuite\b|\bst\b', line, re.I):
                addr_lines.append(line)
        row["address"] = ", ".join(addr_lines[:3])

        # Phone in card text
        row["phone"] = extract_phone(text)

        # Try to get link for detail page
        try:
            link = card.find_element(By.TAG_NAME, "a")
            href = link.get_attribute("href")
            if href and href.startswith("http"):
                row["website"] = href
                # Visit detail page for email
                detail = scrape_detail_page(driver, href)
                row.update({k: v for k, v in detail.items() if v})
        except:
            pass

        return row if row["company_name"] else None
    except Exception as e:
        return None

def scrape_detail_page(driver, url):
    data = {"email": "", "website": "", "phone": ""}
    try:
        main_handle = driver.current_window_handle
        driver.execute_script(f"window.open('{url}','_blank');")
        time.sleep(1.5)
        handles = driver.window_handles
        driver.switch_to.window(handles[-1])
        time.sleep(2)

        body = driver.find_element(By.TAG_NAME, "body").text
        data["email"] = extract_email(body)
        if not data["phone"]:
            data["phone"] = extract_phone(body)

        # Get external website link
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href") or ""
            if href.startswith("http") and "motorolasolutions" not in href and "mpe." not in href:
                data["website"] = href
                break

        driver.close()
        driver.switch_to.window(main_handle)
    except:
        try:
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass
    return data

# ─── REGION SELECTION STRATEGIES ─────────────────────────────────────────────
def try_select_region(driver, region, append_log_fn):
    """Try multiple strategies to filter by region. Returns True if successful."""

    # Strategy 1: URL parameter injection (most reliable for JS SPAs)
    url_variants = [
        f"{BASE_URL}?country={region.replace(' ', '+')}",
        f"{BASE_URL}?region={region.replace(' ', '+')}",
        f"{BASE_URL}?location={region.replace(' ', '+')}",
        f"{BASE_URL}#{region.lower().replace(' ', '-')}",
    ]

    # Strategy 2: Standard <select> dropdown
    try:
        from selenium.webdriver.support.ui import Select
        dd = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
            "select"))
        )
        opts = [o.text.strip().lower() for o in dd.find_elements(By.TAG_NAME, "option")]
        if any(region.lower() in o for o in opts):
            Select(dd).select_by_visible_text(region)
            time.sleep(2.5)
            append_log_fn(f"  ✓ Region set via <select>")
            return True
    except:
        pass

    # Strategy 3: Click a button/tab/li with region name
    try:
        xp = (f"//button[contains(translate(normalize-space(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{region.upper()}')]"
              f"|//li[contains(translate(normalize-space(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{region.upper()}')]"
              f"|//a[contains(translate(normalize-space(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{region.upper()}')]"
              f"|//span[contains(translate(normalize-space(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{region.upper()}')]")
        btn = driver.find_element(By.XPATH, xp)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2.5)
        append_log_fn(f"  ✓ Region set via click
