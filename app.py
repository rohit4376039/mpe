"""
MPE Partner Scraper — Streamlit UI
Persistent across page refreshes using file-based state.
"""

import streamlit as st
import pandas as pd
import time
import re
import os
import json
import threading

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="MPE Partner Scraper", page_icon="📡", layout="wide")

# ─── CONSTANTS ───────────────────────────────────────────────────────────────
BASE_URL    = "https://mpe.motorolasolutions.com/"
CSV_FIELDS  = ["company_name","website","email","program_level","community","region","address","phone"]
STATE_FILE  = "/tmp/mpe_state.json"   # persists between refreshes
LOG_FILE    = "/tmp/mpe_logs.txt"
LOCK        = threading.Lock()

ALL_REGIONS = [
    "United States","Canada","United Kingdom","Australia",
    "Germany","France","India","Brazil","Mexico",
    "Netherlands","Spain","Italy","Sweden","Norway",
    "Denmark","Finland","Poland","Belgium","Switzerland",
    "Austria","South Africa","UAE","Singapore","Japan",
    "South Korea","China","New Zealand","Ireland","Portugal",
    "Czech Republic","Hungary","Romania","Israel",
]

# ─── FILE-BASED STATE HELPERS ────────────────────────────────────────────────
def read_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"running": False, "done": False, "results": []}

def write_state(state):
    with LOCK:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)

def reset_state():
    write_state({"running": False, "done": False, "results": []})
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

def append_log(msg):
    with LOCK:
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")

def read_logs():
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                return f.read()
    except Exception:
        pass
    return ""

def append_result(row):
    with LOCK:
        state = read_state()
        state["results"].append(row)
        write_state(state)

# ─── SCRAPER ─────────────────────────────────────────────────────────────────
def extract_email(text):
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text or "")
    return m.group(0) if m else ""

def extract_phone(text):
    m = re.search(r"(\+?\d[\d\s\-().]{7,})", text or "")
    return m.group(1).strip() if m else ""

def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/122 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)

def scrape_detail_page(driver, url):
    from selenium.webdriver.by import By
    data = {"website":"","email":"","phone":"","address":""}
    try:
        driver.execute_script(f"window.open('{url}','_blank');")
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(2)
        body = driver.find_element(By.TAG_NAME,"body").text
        data["email"] = extract_email(body)
        data["phone"] = extract_phone(body)
        for a in driver.find_elements(By.XPATH,"//a[@href]"):
            href = a.get_attribute("href") or ""
            if href.startswith("http") and "motorola" not in href.lower():
                data["website"] = href
                break
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
    except Exception:
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
    return data

def parse_card(card, driver):
    from selenium.webdriver.by import By
    from selenium.common.exceptions import NoSuchElementException
    text = card.text
    if not text.strip():
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    company_name = lines[0] if lines else ""
    program_level, community = "", ""
    for line in lines:
        low = line.lower()
        if not program_level and any(x in low for x in ["platinum","gold","silver","bronze","authorized","premier","elite"]):
            program_level = line
        if not community and any(x in low for x in ["video","radio","communications","security","software","services","command"]):
            community = line
    detail = {"website":"","email":"","phone":"","address":""}
    try:
        link_el = card.find_element(By.TAG_NAME,"a")
        href = link_el.get_attribute("href") or ""
        if href and href != BASE_URL and "motorolasolutions" in href:
            detail = scrape_detail_page(driver, href)
    except NoSuchElementException:
        pass
    if not detail["email"]:
        detail["email"] = extract_email(text)
    if not detail["website"]:
        for a in card.find_elements(By.TAG_NAME,"a"):
            h = a.get_attribute("href") or ""
            if h.startswith("http") and "motorola" not in h.lower():
                detail["website"] = h
                break
    return {
        "company_name":  company_name,
        "website":       detail["website"],
        "email":         detail["email"],
        "program_level": program_level,
        "community":     community,
        "address":       detail.get("address",""),
        "phone":         detail.get("phone",""),
    }

def run_scraper(regions, scroll_pause, page_pause):
    from selenium.webdriver.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import NoSuchElementException

    append_log("🚀 Scraper started...")
    try:
        driver = make_driver()
        for region in regions:
            append_log(f"▶ Scraping region: {region}")
            try:
                driver.get(BASE_URL)
                time.sleep(3)
                selected = False
                try:
                    from selenium.webdriver.support.ui import Select
                    dd = WebDriverWait(driver,8).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                        "select[name*='country'],select[name*='region'],[data-filter*='country']"))
                    )
                    Select(dd).select_by_visible_text(region)
                    time.sleep(2)
                    selected = True
                except Exception:
                    pass
                if not selected:
                    try:
                        btn = driver.find_element(By.XPATH,
                            f"//button[normalize-space()='{region}']|//li[normalize-space()='{region}']")
                        driver.execute_script("arguments[0].click();",btn)
                        time.sleep(2)
                        selected = True
                    except Exception:
                        pass
                if not selected:
                    append_log(f"  ⚠ Could not select '{region}' – skipping")
                    continue

                page_num = 1
                region_count = 0
                while True:
                    append_log(f"  Page {page_num}…")
                    time.sleep(page_pause)
                    last_h = 0
                    for _ in range(5):
                        driver.execute_script("window.scrollTo(0,document.body.scrollHeight);")
                        time.sleep(scroll_pause)
                        new_h = driver.execute_script("return document.body.scrollHeight")
                        if new_h == last_h:
                            break
                        last_h = new_h
                    driver.execute_script("window.scrollTo(0,0);")

                    cards = driver.find_elements(By.CSS_SELECTOR,
                        ".partner-card,.result-item,[class*='partner'],[class*='result'],.card,article")
                    if not cards:
                        append_log(f"  No cards found on page {page_num}")
                        break
                    for card in cards:
                        try:
                            row = parse_card(card, driver)
                            if row:
                                row["region"] = region
                                append_result(row)
                                region_count += 1
                        except Exception:
                            pass
                    append_log(f"  ✓ {len(cards)} cards | region total: {region_count}")
                    try:
                        nxt = driver.find_element(By.CSS_SELECTOR,
                            "a[aria-label='Next'],button[aria-label='Next'],"
                            ".pagination-next,[class*='next-page']:not([disabled])")
                        if not nxt.is_enabled():
                            break
                        driver.execute_script("arguments[0].click();",nxt)
                        page_num += 1
                    except NoSuchElementException:
                        break
                append_log(f"✅ {region} done — {region_count} partners")
            except Exception as e:
                append_log(f"  ❌ Error in {region}: {e}")
        driver.quit()
    except Exception as e:
        append_log(f"❌ Driver error: {e}")

    # Deduplicate & mark done
    state = read_state()
    seen, unique = set(), []
    for p in state["results"]:
        key = (p["company_name"].lower(), p["region"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    state["results"] = unique
    state["running"] = False
    state["done"] = True
    write_state(state)
    append_log(f"🎉 Complete! {len(unique)} unique partners saved.")

# ─── UI ──────────────────────────────────────────────────────────────────────
state = read_state()

st.title("📡 MPE Partner Scraper")
st.caption("Motorola Solutions PartnerEmpower — Bulk Partner Data Extractor")

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    selected_regions = st.multiselect(
        "Regions to scrape", options=ALL_REGIONS, default=["United States"]
    )
    scroll_pause = st.slider("Scroll pause (sec)", 0.5, 5.0, 1.5, 0.5)
    page_pause   = st.slider("Page load pause (sec)", 1.0, 10.0, 2.0, 0.5)
    st.divider()

    # Status badge
    if state["running"]:
        st.warning("⏳ Scraping in progress…")
        if st.button("🔄 Refresh to update", use_container_width=True):
            st.rerun()
    elif state["done"]:
        st.success(f"✅ Done! {len(state['results'])} partners")
    else:
        st.info("💡 Start with 1 region to test first.")

# ── Top action row ───────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2,2,3])

with col1:
    if not state["running"]:
        if st.button("🚀 Start Scraping", type="primary",
                     disabled=not selected_regions, use_container_width=True):
            reset_state()
            write_state({"running": True, "done": False, "results": []})
            t = threading.Thread(
                target=run_scraper,
                args=(selected_regions, scroll_pause, page_pause),
                daemon=True,
            )
            t.start()
            time.sleep(1)
            st.rerun()
    else:
        if st.button("🔄 Refresh Results", use_container_width=True, type="primary"):
            st.rerun()

with col2:
    if st.button("🗑️ Clear / Reset", use_container_width=True, disabled=state["running"]):
        reset_state()
        st.rerun()

with col3:
    results = state["results"]
    if results:
        df_dl = pd.DataFrame(results, columns=CSV_FIELDS)
        st.download_button(
            "⬇️ Download CSV",
            data=df_dl.to_csv(index=False).encode("utf-8"),
            file_name="mpe_partners.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.button("⬇️ Download CSV", disabled=True, use_container_width=True)

st.divider()

# ── Metrics ──────────────────────────────────────────────────────────────────
results = state["results"]
m1,m2,m3,m4 = st.columns(4)
m1.metric("Total Partners",  len(results))
m2.metric("With Email",      sum(1 for r in results if r.get("email")))
m3.metric("With Website",    sum(1 for r in results if r.get("website")))
m4.metric("Regions Done",    len(set(r.get("region","") for r in results)))

st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📋 Results Table", "📜 Live Logs"])

with tab1:
    if results:
        df = pd.DataFrame(results, columns=CSV_FIELDS)
        fc1,fc2,fc3 = st.columns(3)
        with fc1:
            f_region = st.multiselect("Filter Region",
                options=sorted(df["region"].unique()), key="f_reg")
        with fc2:
            f_level = st.multiselect("Filter Program Level",
                options=sorted(df["program_level"].dropna().unique()), key="f_lvl")
        with fc3:
            f_search = st.text_input("Search company", key="f_srch")

        filtered = df.copy()
        if f_region:  filtered = filtered[filtered["region"].isin(f_region)]
        if f_level:   filtered = filtered[filtered["program_level"].isin(f_level)]
        if f_search:  filtered = filtered[filtered["company_name"].str.contains(f_search, case=False, na=False)]

        st.dataframe(filtered, use_container_width=True, height=420)
        st.caption(f"Showing {len(filtered)} of {len(df)} records")
    else:
        st.info("No data yet. Configure settings and click **Start Scraping**.")

with tab2:
    logs = read_logs()
    if logs:
        st.text_area("Logs", logs, height=420, key="log_area")
        if state["running"]:
            st.caption("🔄 Click **Refresh Results** in the sidebar or top-left to update logs.")
    else:
        st.info("Logs will appear here once scraping starts.")

# ── Auto-refresh while running ───────────────────────────────────────────────
if state["running"]:
    time.sleep(5)
    st.rerun()
