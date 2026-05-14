# MPE Partner Scraper — Streamlit App

## Run Locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Open: http://localhost:8501

## Deploy FREE on Streamlit Community Cloud

1. Push this folder to a **GitHub repo** (public or private)
2. Go to https://share.streamlit.io
3. Click **"New app"** → select your repo → set main file: `app.py`
4. Click **Deploy** — live URL in ~2 minutes ✅

> Streamlit Cloud installs packages.txt (system) + requirements.txt (Python) automatically.

## How to Use
1. Select regions from the sidebar (start with 1 to test)
2. Adjust scroll/page pause if needed
3. Click **Start Scraping**
4. Watch live logs in the **Live Logs** tab
5. Click **Download CSV** when done

## Columns in CSV
company_name, website, email, program_level, community, region, address, phone
