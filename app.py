"""
MPE Partner Scraper — Streamlit UI
"""

import streamlit as st
import pandas as pd
import time
import csv
import re
import io
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MPE Partner Scraper",
    page_icon="📡",
    layout="wide",
)

# ─── CONSTANTS ───────────────────────────────────────────────────────────────
BASE_URL   = "https://mpe.motorolasolutions.com/"
CSV_FIELDS = ["company_name", "website", "email", "program_level", "community", "region", "address", "phone"]

ALL_REGIONS = [
    "United States", "Canada", "United Kingdom", "Australia",
    "Germany", "France", "India", "Brazil", "Mexico",
    "Netherlands", "Spain", "Italy", "Sweden", "Norway",
    "Denmark", "Finland", "Poland", "Belgium", "Switzerland",
    "Austria", "South Africa", "UAE", "Singapore", "Japan",
    "South Korea", "China", "New Zealand", "Ireland", "Portugal",
    "Czech Republic", "Hungary", "Romania", "Israel",
]

# ─── SESSION STATE ───────────────────────────────────────────────────────────
for key, default in [
    ("running", False),
    ("results", []),
    ("logs", []),
    ("done", False),
    ("error", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─── SCRAPER FUNCTIONS ───────────────────────────────────────────────────────
def make_driver():
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


def extract_email(text):
    m = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text or "")
    return m.group(0) if m else ""


def extract_phone(text):
    m = re.search(r"(\+?\d[\d\s\-().]{7,})", text or "")
    return m.group(1).strip() if m else ""


def scrape_detail_page(driver, url):
    data = {"website": "", "email": "", "phone": "", "address": ""}
    try:
        driver.execute_script(f"window.open('{url}', '_blank');")
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(2)
        body = driver.find_element(By.TAG_NAME, "body").text
        data["email"] = extract_email(body)
        data["phone"] = extract_phone(body)
        for a in driver.find_elements(By.XPATH, "//a[@href]"):
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
    text = card.text
    if not text.strip():
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    company_name  = lines[0] if lines else ""
    program_level, community = "", ""
    for line in lines:
        low = line.lower()
        if not program_level and any(x in low for x in ["platinum","gold","silver","bronze","authorized","premier","elite"]):
            program_level = line
        if not community and any(x in low for x in ["video","radio","communications","security","software","services","command"]):
            community = line
    detail = {"website": "", "email": "", "phone": "", "address": ""}
    try:
        link_el = card.find_element(By.TAG_NAME, "a")
        href = link_el.get_attribute("href") or ""
        if href and href != BASE_URL and "motorolasolutions" in href:
            detail = scrape_detail_page(driver, href)
    except NoSuchElementException:
        pass
    if not detail["email"]:
        detail["email"] = extract_email(text)
    if not detail["website"]:
        for a in card.find_elements(By.TAG_NAME, "a"):
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


def run_scraper(regions, scroll_pause, page_pause, log_cb, result_cb, done_cb):
    all_partners = []
    try:
        driver = make_driver()
        for region in regions:
            log_cb(f"▶ Scraping region: {region}")
            partners = []
            try:
                driver.get(BASE_URL)
                time.sleep(3)
                selected = False
                # Try dropdown
                try:
                    from selenium.webdriver.support.ui import Select
                    dd = WebDriverWait(driver, 8).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                        "select[name*='country'], select[name*='region'], [data-filter*='country']"))
                    )
                    Select(dd).select_by_visible_text(region)
                    time.sleep(2)
                    selected = True
                except Exception:
                    pass
                # Try button
                if not selected:
                    try:
                        btn = driver.find_element(By.XPATH,
                            f"//button[normalize-space()='{region}'] | //li[normalize-space()='{region}']")
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(2)
                        selected = True
                    except Exception:
                        pass
                if not selected:
                    log_cb(f"  ⚠ Could not select '{region}' – skipping")
                    continue

                page_num = 1
                while True:
                    log_cb(f"  Page {page_num}…")
                    time.sleep(page_pause)
                    # Scroll
                    last_h = 0
                    for _ in range(5):
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(scroll_pause)
                        new_h = driver.execute_script("return document.body.scrollHeight")
                        if new_h == last_h:
                            break
                        last_h = new_h
                    driver.execute_script("window.scrollTo(0, 0);")

                    cards = driver.find_elements(By.CSS_SELECTOR,
                        ".partner-card, .result-item, [class*='partner'], [class*='result'], .card, article")
                    if not cards:
                        log_cb(f"  No cards found on page {page_num}")
                        break
                    for card in cards:
                        try:
                            row = parse_card(card, driver)
                            if row:
                                row["region"] = region
                                partners.append(row)
                                result_cb(row)
                        except Exception:
                            pass
                    log_cb(f"  ✓ {len(cards)} cards | region total: {len(partners)}")
                    try:
                        nxt = driver.find_element(By.CSS_SELECTOR,
                            "a[aria-label='Next'], button[aria-label='Next'], "
                            ".pagination-next, [class*='next-page']:not([disabled])")
                        if not nxt.is_enabled():
                            break
                        driver.execute_script("arguments[0].click();", nxt)
                        page_num += 1
                    except NoSuchElementException:
                        break
            except Exception as e:
                log_cb(f"  ❌ Error in {region}: {e}")
            all_partners.extend(partners)
            log_cb(f"✅ {region} done — {len(partners)} partners")
        driver.quit()
    except Exception as e:
        log_cb(f"❌ Driver error: {e}")
    done_cb(all_partners)


# ─── UI ──────────────────────────────────────────────────────────────────────
st.title("📡 MPE Partner Scraper")
st.caption("Motorola Solutions PartnerEmpower — Bulk Partner Data Extractor")

# ── Sidebar config ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    selected_regions = st.multiselect(
        "Regions to scrape",
        options=ALL_REGIONS,
        default=["United States"],
        help="Select one or more regions"
    )
    scroll_pause = st.slider("Scroll pause (sec)", 0.5, 5.0, 1.5, 0.5)
    page_pause   = st.slider("Page load pause (sec)", 1.0, 10.0, 2.0, 0.5)
    st.divider()
    st.info("💡 Start with 1 region to test before running all.")

# ── Main area ────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 2, 3])

with col1:
    start_btn = st.button(
        "🚀 Start Scraping",
        disabled=st.session_state.running or not selected_regions,
        use_container_width=True,
        type="primary",
    )

with col2:
    clear_btn = st.button("🗑️ Clear Results", use_container_width=True,
                          disabled=st.session_state.running)

with col3:
    if st.session_state.results:
        df = pd.DataFrame(st.session_state.results, columns=CSV_FIELDS)
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download CSV",
            data=csv_bytes,
            file_name="mpe_partners.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.button("⬇️ Download CSV", disabled=True, use_container_width=True)

st.divider()

# ── Stats row ────────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
results = st.session_state.results
m1.metric("Total Partners", len(results))
m2.metric("With Email", sum(1 for r in results if r.get("email")))
m3.metric("With Website", sum(1 for r in results if r.get("website")))
m4.metric("Regions Done", len(set(r.get("region","") for r in results)))

st.divider()

# ── Results table ─────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📋 Results Table", "📜 Live Logs"])

with tab1:
    if results:
        df_display = pd.DataFrame(results, columns=CSV_FIELDS)
        # Filters
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_region = st.multiselect("Filter Region", options=sorted(df_display["region"].unique()), key="f_reg")
        with fc2:
            f_level  = st.multiselect("Filter Program Level", options=sorted(df_display["program_level"].dropna().unique()), key="f_lvl")
        with fc3:
            f_search = st.text_input("Search company name", key="f_srch")

        filtered = df_display.copy()
        if f_region:
            filtered = filtered[filtered["region"].isin(f_region)]
        if f_level:
            filtered = filtered[filtered["program_level"].isin(f_level)]
        if f_search:
            filtered = filtered[filtered["company_name"].str.contains(f_search, case=False, na=False)]

        st.dataframe(filtered, use_container_width=True, height=420)
        st.caption(f"Showing {len(filtered)} of {len(df_display)} records")
    else:
        st.info("No data yet. Configure settings and click **Start Scraping**.")

with tab2:
    log_box = st.empty()
    if st.session_state.logs:
        log_box.text_area("Logs", "\n".join(st.session_state.logs[-100:]), height=400, key="log_area")
    else:
        st.info("Logs will appear here once scraping starts.")

# ── Actions ───────────────────────────────────────────────────────────────────
if clear_btn:
    st.session_state.results = []
    st.session_state.logs    = []
    st.session_state.done    = False
    st.session_state.error   = ""
    st.rerun()

if start_btn and not st.session_state.running:
    st.session_state.running = True
    st.session_state.results = []
    st.session_state.logs    = []
    st.session_state.done    = False

    def log_cb(msg):
        st.session_state.logs.append(msg)

    def result_cb(row):
        st.session_state.results.append(row)

    def done_cb(all_data):
        # Deduplicate
        seen, unique = set(), []
        for p in all_data:
            key = (p["company_name"].lower(), p["region"].lower())
            if key not in seen:
                seen.add(key)
                unique.append(p)
        st.session_state.results = unique
        st.session_state.running = False
        st.session_state.done    = True
        log_cb(f"🎉 Scraping complete! {len(unique)} unique partners saved.")

    t = threading.Thread(
        target=run_scraper,
        args=(selected_regions, scroll_pause, page_pause, log_cb, result_cb, done_cb),
        daemon=True,
    )
    t.start()
    st.rerun()

if st.session_state.running:
    st.warning("⏳ Scraping in progress… Refresh the page to see latest results.")
    time.sleep(3)
    st.rerun()

if st.session_state.done:
    st.success(f"✅ Done! {len(st.session_state.results)} unique partners scraped.")
