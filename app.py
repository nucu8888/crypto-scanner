import time
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="Crypto Futures Scanner", layout="wide")

# Endpoint-uri REST
BINANCE_FUTURES_REST = "https://fapi.binance.com"
BYBIT_REST = "https://api.bybit.com"
PHEMEX_REST = "https://api.phemex.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

TF_MAP = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
TF_BINANCE = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
TF_BYBIT = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}

def safe_float(x):
    try: return float(x)
    except: return None

def human_num(x):
    if x is None: return ""
    try: v = float(x)
    except: return ""
    av = abs(v)
    if av >= 1e9: return f"${v/1e9:.1f}B"
    if av >= 1e6: return f"${v/1e6:.1f}M"
    if av >= 1e3: return f"${v/1e3:.1f}K"
    return f"${v:.1f}"

def http_get_json(url, params=None, timeout=8):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None

def fetch_tickers_bybit():
    j = http_get_json(f"{BYBIT_REST}/v5/market/tickers", params={"category": "linear"})
    results = []
    if j and j.get("retCode") == 0:
        for t in j.get("result", {}).get("list", []):
            sym = t.get("symbol", "")
            if sym.endswith("USDT"):
                price = safe_float(t.get("lastPrice"))
                vol = safe_float(t.get("turnover24h"))
                chg = safe_float(t.get("price24hPcnt"))
                if chg is not None: chg *= 100.0
                if price:
                    results.append({
                        "Symbol": sym,
                        "Price": price,
                        "Vol 24H ($)": vol,
                        "Δ 24H (%)": chg
                    })
    return pd.DataFrame(results)

def fetch_tickers_binance():
    j = http_get_json(f"{BINANCE_FUTURES_REST}/fapi/v1/ticker/24hr")
    results = []
    if isinstance(j, list):
        for t in j:
            sym = t.get("symbol", "")
            if sym.endswith("USDT"):
                price = safe_float(t.get("lastPrice"))
                vol = safe_float(t.get("quoteVolume"))
                chg = safe_float(t.get("priceChangePercent"))
                if price:
                    results.append({
                        "Symbol": sym,
                        "Price": price,
                        "Vol 24H ($)": vol,
                        "Δ 24H (%)": chg
                    })
    return pd.DataFrame(results)

def fetch_tickers_phemex():
    j = http_get_json(f"{PHEMEX_REST}/md/v3/ticker/24hr/all")
    results = []
    if j and j.get("result"):
        res = j["result"]
        if isinstance(res, list):
            for t in res:
                sym = t.get("symbol", "")
                if sym.endswith("USDT") or sym.startswith("c"):
                    vol = safe_float(t.get("turnoverEv")) or safe_float(t.get("turnover")) or safe_float(t.get("volume24h"))
                    if vol and vol > 1e7: vol /= 1e8
                    open_p = safe_float(t.get("openPrice"))
                    close_p = safe_float(t.get("closePrice")) or safe_float(t.get("lastPrice"))
                    if open_p and open_p > 1e7: open_p /= 1e8
                    if close_p and close_p > 1e7: close_p /= 1e8
                    chg = ((close_p - open_p) / open_p * 100.0) if (open_p and close_p and open_p > 0) else None
                    if close_p:
                        results.append({
                            "Symbol": sym,
                            "Price": close_p,
                            "Vol 24H ($)": vol,
                            "Δ 24H (%)": chg
                        })
    return pd.DataFrame(results)

@st.cache_data(ttl=60, show_spinner=False)
def load_data(exchange):
    if exchange == "Bybit Futures":
        df = fetch_tickers_bybit()
    elif exchange == "Binance Futures":
        df = fetch_tickers_binance()
    else:
        df = fetch_tickers_phemex()
    return df

# --- INTERFAȚĂ STREMLIT ---
st.title("🚀 Real-Time Crypto Futures Scanner")

col1, col2 = st.columns([3, 3])
with col1:
    exchange = st.selectbox("Selectează Bursa", ["Bybit Futures", "Binance Futures", "Phemex Futures"])
with col2:
    st.write("")
    if st.button("🔄 Actualizează Datele"):
        st.cache_data.clear()
        st.rerun()

st.caption("⚡ Datele sunt partajate și salvate în cache timp de 60s pe server.")

with st.spinner(f"Preluare date de pe {exchange}..."):
    df = load_data(exchange)

if df is None or df.empty:
    st.error(f"⚠️ Nu s-au putut prelua date de la {exchange}. IP-ul serverului Cloud este temporar limitat. Încearcă să schimbi bursa pe Bybit Futures.")
else:
    st.subheader(f"Rezultate ({len(df)} monede Futures)")
    
    top_option = st.radio("Sortează după:", ["Volume (24H)", "Gaineri (% 24H)", "Loseri (% 24H)"], horizontal=True)

    if top_option == "Volume (24H)":
        df = df.sort_values(by="Vol 24H ($)", ascending=False)
    elif top_option == "Gaineri (% 24H)":
        df = df.sort_values(by="Δ 24H (%)", ascending=False)
    elif top_option == "Loseri (% 24H)":
        df = df.sort_values(by="Δ 24H (%)", ascending=True)

    display_df = df.copy()
    display_df["Vol 24H ($)"] = display_df["Vol 24H ($)"].apply(human_num)
    display_df["Price"] = display_df["Price"].apply(lambda x: f"${x:.4f}" if x >= 1 else f"${x:.7f}")
    display_df["Δ 24H (%)"] = display_df["Δ 24H (%)"].apply(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "-")

    st.dataframe(display_df, use_container_width=True, height=500)
