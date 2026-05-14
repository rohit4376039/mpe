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
            append_log_fn(   "OK Region set via select")
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
        append_log_fn("  OK Region set via click on text element")
        return True
    except:
        pass

    # Strategy 4: JavaScript-based — set value on any input that looks like a filter
    try:
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='country' i],input[placeholder*='region' i],input[placeholder*='location' i],input[placeholder*='search' i]")
        for inp in inputs:
            try:
                driver.execute_script("arguments[0].value = arguments[1];", inp, region)
                inp.send_keys(" ")  # trigger React onChange
                time.sleep(1)
                # Look for autocomplete dropdown
                suggestions = driver.find_elements(By.CSS_SELECTOR, "[class*='suggestion'],[class*='autocomplete'],[class*='dropdown'] li,[role='option']")
                for s in suggestions:
                    if region.lower() in s.text.lower():
                        s.click()
                        time.sleep(2)
                        append_log_fn("  OK Region set via input+autocomplete")
                        return True
            except:
                continue
    except:
        pass

    # Strategy 5: Dump page HTML to log for manual debugging
    try:
        src = driver.page_source
        # Find region-related HTML snippets
        lower = src.lower()
        idx = lower.find("united states")
        if idx == -1:
            idx = lower.find("country")
        if idx == -1:
            idx = lower.find("region")
        if idx >= 0:
            snippet = src[max(0, idx-200):idx+400].replace("\n", " ")
            append_log_fn(f"  🔍 DOM snippet near 'region/country': ...{snippet[:400]}...")
        else:
            append_log_fn(f"  🔍 Page title: {driver.title}")
            append_log_fn(f"  🔍 Body preview: {driver.find_element(By.TAG_NAME,'body').text[:300]}")
    except:
        pass

    return False

# ─── MAIN SCRAPER ─────────────────────────────────────────────────────────────
def run_scraper(regions, scroll_pause, page_pause, no_filter_mode):
    state = read_state()
    state["running"] = True
    state["done"] = False
    write_state(state)

    append_log("🚀 Scraper started...")
    try:
        driver = make_driver()
        append_log("✅ Chrome driver started successfully")
    except Exception as e:
        append_log(f"❌ Failed to start Chrome driver: {e}")
        state["running"] = False; state["done"] = True
        write_state(state)
        return

    try:
        if no_filter_mode:
            # ── NO-FILTER MODE: scrape all pages without region selection ──
            append_log("📋 No-filter mode: scraping all results directly...")
            driver.get(BASE_URL)
            time.sleep(page_pause + 2)
            append_log(f"  Page title: {driver.title}")

            page_num = 1
            total = 0
            while True:
                append_log(f"  Page {page_num}…")
                time.sleep(page_pause)
                scroll_page(driver, scroll_pause)

                cards, selector_used = find_cards(driver)
                if not cards:
                    body_text = driver.find_element(By.TAG_NAME, "body").text
                    append_log(f"  ⚠ No cards found with any selector.")
                    append_log(f"  Page title: {driver.title}")
                    append_log(f"  Body (first 500): {body_text[:500]}")
                    break

                append_log(f"  Found {len(cards)} cards using: {selector_used}")
                for card in cards:
                    try:
                        row = parse_card(card, driver)
                        if row:
                            row["region"] = "All"
                            append_result(row)
                            total += 1
                    except Exception as ce:
                        append_log(f"  Card error: {ce}")

                append_log(f"  [OK] Page {page_num} done | running total: {total}")

                # Next page
                try:
                    nxt = driver.find_element(By.CSS_SELECTOR,
                        "a[aria-label*='next' i],button[aria-label*='next' i],"
                        "[class*='next'][class*='page']:not([disabled]),"
                        "[class*='pagination'] a:last-child,[rel='next']")
                    if not nxt.is_enabled() or "disabled" in (nxt.get_attribute("class") or ""):
                        break
                    driver.execute_script("arguments[0].click();", nxt)
                    page_num += 1
                    time.sleep(page_pause)
                except NoSuchElementException:
                    break

            append_log(f"✅ Done — {total} partners found (no-filter mode)")

        else:
            # ── REGION MODE ──
            for region in regions:
                append_log(f"▶ Scraping region: {region}")
                region_count = 0
                try:
                    driver.get(BASE_URL)
                    time.sleep(page_pause + 1)

                    selected = try_select_region(driver, region, append_log)

                    if not selected:
                        append_log(f"  ⚠ Could not select '{region}' – trying no-filter fallback for this region")
                        # Still try to scrape current page
                    else:
                        time.sleep(page_pause)

                    page_num = 1
                    while True:
                        append_log(f"  Page {page_num}…")
                        time.sleep(page_pause)
                        scroll_page(driver, scroll_pause)

                        cards, selector_used = find_cards(driver)
                        if not cards:
                            body_text = driver.find_element(By.TAG_NAME, "body").text
                            append_log(f"  ⚠ No cards. Selector tried. Body: {body_text[:300]}")
                            break

                        append_log(f"  Found {len(cards)} cards [{selector_used}]")
                        for card in cards:
                            try:
                                row = parse_card(card, driver)
                                if row:
                                    row["region"] = region
                                    append_result(row)
                                    region_count += 1
                            except Exception as ce:
                                append_log(f"  Card error: {ce}")

                        append_log(f"  [OK] {len(cards)} cards | region total: {region_count}")

                        try:
                            nxt = driver.find_element(By.CSS_SELECTOR,
                                "a[aria-label*='next' i],button[aria-label*='next' i],"
                                "[class*='next'][class*='page']:not([disabled]),"
                                "[class*='pagination'] a:last-child,[rel='next']")
                            if not nxt.is_enabled() or "disabled" in (nxt.get_attribute("class") or ""):
                                break
                            driver.execute_script("arguments[0].click();", nxt)
                            page_num += 1
                        except NoSuchElementException:
                            break

                    append_log(f"✅ {region} done — {region_count} partners")
                except Exception as e:
                    append_log(f"  ❌ Error in {region}: {e}")

        driver.quit()
    except Exception as e:
        append_log(f"❌ Scraper error: {e}")
        try: driver.quit()
        except: pass

    # Deduplicate
    state = read_state()
    seen, unique = set(), []
    for p in state["results"]:
        key = (p.get("company_name","").lower(), p.get("region","").lower())
        if key not in seen and key[0]:
            seen.add(key)
            unique.append(p)
    state["results"] = unique
    state["running"] = False
    state["done"] = True
    write_state(state)
    append_log(f"🏁 Scraping complete. {len(unique)} unique partners saved.")

# ─── UI ──────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="MPE Partner Scraper", page_icon="📡", layout="wide")

# Init state
if not os.path.exists(STATE_FILE):
    reset_state()

state = read_state()

# ── Sidebar ──
with st.sidebar:
    st.title("⚙️ Settings")

    mode = st.radio("Scrape mode", ["No Filter (scrape all)", "By Region"], index=0,
        help="'No Filter' scrapes all partners at once — best when region filter can't be detected.")

    no_filter_mode = (mode == "No Filter (scrape all)")

    if not no_filter_mode:
        selected_regions = st.multiselect("Regions to scrape", ALL_REGIONS, default=["United States"])
    else:
        selected_regions = ["All"]

    scroll_pause = st.slider("Scroll pause (sec)", 0.5, 5.0, 1.5, 0.25)
    page_pause   = st.slider("Page load pause (sec)", 1.0, 8.0, 3.0, 0.5)

    st.divider()
    if state.get("done"):
        st.success(f"✅ Done! {len(state.get('results',[]))} partners")
    elif state.get("running"):
        st.warning("⏳ Scraping in progress...")
        st.button("🔄 Refresh to update", on_click=lambda: None)
    else:
        st.info("💡 Use 'No Filter' mode first to test.")

# ── Header ──
st.title("📡 MPE Partner Scraper")
st.caption("Motorola Solutions PartnerEmpower — Bulk Partner Data Extractor")

col1, col2, col3 = st.columns(3)
with col1:
    start_disabled = state.get("running", False)
    if st.button("🚀 Start Scraping", disabled=start_disabled, use_container_width=True, type="primary"):
        reset_state()
        t = threading.Thread(
            target=run_scraper,
            args=(selected_regions, scroll_pause, page_pause, no_filter_mode),
            daemon=True
        )
        t.start()
        st.rerun()

with col2:
    if st.button("🗑️ Clear / Reset", use_container_width=True):
        reset_state()
        st.rerun()

with col3:
    results = state.get("results", [])
    if results:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(results)
        st.download_button("⬇️ Download CSV", buf.getvalue(), "mpe_partners.csv", "text/csv", use_container_width=True)
    else:
        st.button("⬇️ Download CSV", disabled=True, use_container_width=True)

st.divider()

# ── Metrics ──
results = state.get("results", [])
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Partners",  len(results))
m2.metric("With Email",      sum(1 for r in results if r.get("email")))
m3.metric("With Website",    sum(1 for r in results if r.get("website")))
m4.metric("Regions Done",    len(set(r.get("region","") for r in results)))

st.divider()

# ── Tabs ──
tab1, tab2 = st.tabs(["📋 Results Table", "🪵 Live Logs"])

with tab1:
    if results:
        import pandas as pd
        df = pd.DataFrame(results, columns=CSV_FIELDS)
        c1, c2, c3 = st.columns([2,2,3])
        with c1:
            f_region = st.multiselect("Filter Region", options=sorted(df["region"].unique()), key="f_reg")
        with c2:
            f_level = st.multiselect("Filter Program Level", options=sorted(df["program_level"].dropna().unique()), key="f_lvl")
        with c3:
            f_search = st.text_input("Search company name", key="f_srch")
        filtered = df.copy()
        if f_region: filtered = filtered[filtered["region"].isin(f_region)]
        if f_level:  filtered = filtered[filtered["program_level"].isin(f_level)]
        if f_search: filtered = filtered[filtered["company_name"].str.contains(f_search, case=False, na=False)]
        st.dataframe(filtered, use_container_width=True, height=420)
        st.caption(f"Showing {len(filtered)} of {len(df)} records")
    else:
        st.info("No results yet. Start scraping to populate the table.")

with tab2:
    logs = read_logs()
    st.text_area("Logs", value=logs if logs else "Logs will appear here once scraping starts.", height=400, label_visibility="collapsed")
    if state.get("running"):
        st.button("🔄 Refresh logs", on_click=lambda: None, key="refresh_logs")
