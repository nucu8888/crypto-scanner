import time
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="Crypto Futures Scanner", layout="wide")

PHEMEX_REST = "https://api.phemex.com"
VAPI_REST = "https://vapi.phemex.com"
BINANCE_FUTURES_REST = "https://fapi.binance.com"
BYBIT_REST = "https://api.bybit.com"

# Header mai complet pentru a nu fi blocat pe servere cloud
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

TF_MAP = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
TF_BINANCE = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
TF_BYBIT = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}

MAX_WORKERS = 8

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

def http_get_json(url, params=None, timeout=10):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code >= 400: return None
        return r.json()
    except:
        return None

def parse_ohlcv(rows):
    opens, highs, lows, closes, volumes = [], [], [], [], []
    for r in rows:
        try:
            if len(r) < 6: continue
            o, h, l = float(r[3]), float(r[4]), float(r[5])
            c, v = float(r[6]), float(r[7])
            if h > 1e7 and not any(k in str(r) for k in ["SHIB", "PEPE", "BONK"]): 
                o /= 1e8; h /= 1e8; l /= 1e8; c /= 1e8
            if v > 1e10: v /= 1e8
            opens.append(o); highs.append(h); lows.append(l); closes.append(c); volumes.append(v)
        except: continue
    return opens, highs, lows, closes, volumes

def fetch_all_futures_symbols_and_tickers(exchange):
    out_tickers, symbols_list = {}, []
    if exchange == "Phemex Futures":
        j = http_get_json(f"{PHEMEX_REST}/md/v3/ticker/24hr/all")
        if j and j.get("result"):
            res = j["result"]
            if isinstance(res, list):
                for t in res:
                    sym = t.get("symbol", "")
                    if sym.endswith("USDT") or sym.startswith("c"):
                        raw_turnover = safe_float(t.get("turnoverEv")) or safe_float(t.get("turnover")) or safe_float(t.get("volume24h"))
                        if raw_turnover and raw_turnover > 1e7: raw_turnover /= 1e8
                        open_p = safe_float(t.get("openPrice"))
                        close_p = safe_float(t.get("closePrice")) or safe_float(t.get("lastPrice"))
                        if open_p and open_p > 1e7: open_p /= 1e8
                        if close_p and close_p > 1e7: close_p /= 1e8
                        delta_24 = ((close_p - open_p) / open_p * 100.0) if (open_p and close_p and open_p > 0) else None
                        out_tickers[sym] = {"turnoverRv": raw_turnover, "changePercent": delta_24}
                        symbols_list.append(sym)
    elif exchange == "Binance Futures":
        j = http_get_json(f"{BINANCE_FUTURES_REST}/fapi/v1/ticker/24hr")
        if isinstance(j, list):
            for t in j:
                sym = t.get("symbol", "")
                if sym.endswith("USDT"):
                    out_tickers[sym] = {"turnoverRv": safe_float(t.get("quoteVolume")), "changePercent": safe_float(t.get("priceChangePercent"))}
                    symbols_list.append(sym)
    elif exchange == "Bybit Futures":
        j = http_get_json(f"{BYBIT_REST}/v5/market/tickers", params={"category": "linear"})
        if j and j.get("retCode") == 0:
            for t in j.get("result", {}).get("list", []):
                sym = t.get("symbol", "")
                if sym.endswith("USDT"):
                    raw_change = safe_float(t.get("price24hPcnt"))
                    if raw_change is not None: raw_change *= 100.0
                    out_tickers[sym] = {"turnoverRv": safe_float(t.get("turnover24h")), "changePercent": raw_change}
                    symbols_list.append(sym)
    return symbols_list, out_tickers

def fetch_klines(exchange, symbol, tf_str):
    if exchange == "Phemex Futures":
        params = {"symbol": symbol, "resolution": TF_MAP.get(tf_str, 3600), "limit": 200}
        for base in (VAPI_REST, PHEMEX_REST):
            j = http_get_json(base + "/exchange/public/md/v2/kline/last", params=params)
            if j and (j.get("code") == 0 or j.get("code") is None):
                r = j.get("data", {}).get("rows") or j.get("rows") or []
                if r: return r
    elif exchange == "Binance Futures":
        j = http_get_json(f"{BINANCE_FUTURES_REST}/fapi/v1/klines", params={"symbol": symbol, "interval": TF_BINANCE.get(tf_str, "1h"), "limit": 150})
        if isinstance(j, list): return [[item[0], 0, 0, item[1], item[2], item[3], item[4], item[5]] for item in j]
    elif exchange == "Bybit Futures":
        j = http_get_json(f"{BYBIT_REST}/v5/market/kline", params={"category": "linear", "symbol": symbol, "interval": TF_BYBIT.get(tf_str, "60"), "limit": 150})
        if j and j.get("retCode") == 0:
            list_data = j.get("result", {}).get("list", [])
            list_data.reverse()
            return [[item[0], 0, 0, item[1], item[2], item[3], item[4], item[5]] for item in list_data]
    return []

def build_symbol_row(sym, exchange, tickers, tf_str):
    try:
        t = tickers.get(sym, {})
        vol_24h, delta_24h = safe_float(t.get("turnoverRv")), t.get("changePercent")
        rows = fetch_klines(exchange, sym, tf_str)
        opens, highs, lows, closes, volumes = parse_ohlcv(rows)
        if not closes or len(closes) < 2: return None
        
        current_price = closes[-1]
        candles_24h = max(1, int(86400 / TF_MAP.get(tf_str, 3600)))
        if delta_24h is None and len(closes) > candles_24h:
            past_p = closes[-(candles_24h + 1)]
            if past_p > 0: delta_24h = ((current_price - past_p) / past_p) * 100.0

        rel_vol = None
        if len(volumes) >= 5 and current_price:
            count_tf = min(20, len(volumes)-1)
            penultimate = volumes[-(count_tf+1):-1]
            if len(penultimate) > 0:
                v20 = (sum(penultimate) / float(len(penultimate))) * current_price
                if v20 > 0: rel_vol = (volumes[-1] * current_price) / v20

        return {
            "Symbol": sym,
            "Price": current_price,
            "Vol 24H ($)": vol_24h,
            "Δ 24H (%)": delta_24h,
            "Rel Vol (TF)": rel_vol,
            "raw_closes": closes
        }
    except: return None

@st.cache_data(ttl=90, show_spinner=False)
def get_cached_scan_data(exchange, tf_str):
    symbols, tickers = fetch_all_futures_symbols_and_tickers(exchange)
    results = []
    # Limităm numărul de monede scanate per interogare pe serverul cloud pentru a preveni IP Ban
    scan_symbols = symbols[:120] if len(symbols) > 120 else symbols
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(build_symbol_row, sym, exchange, tickers, tf_str): sym for sym in scan_symbols}
        for f in as_completed(futures):
            res = f.result()
            if res: results.append(res)
    return pd.DataFrame(results)

# --- INTERFAȚĂ ---
st.title("🚀 Real-Time Crypto Futures Scanner")

col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    exchange = st.selectbox("Bursă", ["Phemex Futures", "Binance Futures", "Bybit Futures"])
with col2:
    tf_str = st.selectbox("Timeframe", list(TF_MAP.keys()), index=4)
with col3:
    st.write("")
    if st.button("🔄 Force Refresh Cache"):
        st.cache_data.clear()
        st.rerun()

with st.spinner(f"Scanare {exchange} ({tf_str})... Te rugăm să aștepți..."):
    df = get_cached_scan_data(exchange, tf_str)

if df.empty:
    st.warning("⚠️ Nu s-au putut prelua date de la bursă (posibil limitare API temporară de pe IP-ul serverului). Încearcă să schimbi bursa pe Binance Futures sau Bybit Futures.")
else:
    st.subheader("🔥 Top-uri & Filtrare")
    top_option = st.radio("Sortează după:", ["Volume (24H)", "Gaineri (% 24H)", "Loseri (% 24H)", "Rel Vol (Volum Neobișnuit)"], horizontal=True)

    if top_option == "Volume (24H)":
        df = df.sort_values(by="Vol 24H ($)", ascending=False)
    elif top_option == "Gaineri (% 24H)":
        df = df.sort_values(by="Δ 24H (%)", ascending=False)
    elif top_option == "Loseri (% 24H)":
        df = df.sort_values(by="Δ 24H (%)", ascending=True)
    elif top_option == "Rel Vol (Volum Neobișnuit)":
        df = df.sort_values(by="Rel Vol (TF)", ascending=False)

    display_df = df.copy()
    display_df["Vol 24H ($)"] = display_df["Vol 24H ($)"].apply(human_num)
    display_df["Price"] = display_df["Price"].apply(lambda x: f"${x:.4f}" if x >= 1 else f"${x:.7f}")
    display_df["Δ 24H (%)"] = display_df["Δ 24H (%)"].apply(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "-")
    display_df["Rel Vol (TF)"] = display_df["Rel Vol (TF)"] .apply(lambda x: f"{x:.2f}x" if pd.notnull(x) else "-")

    st.dataframe(display_df.drop(columns=["raw_closes"]), use_container_width=True, height=450)

    st.divider()
    selected_symbol = st.selectbox("Selectează moneda pentru vizualizare grafic:", df["Symbol"].tolist())
    
    selected_row = df[df["Symbol"] == selected_symbol].iloc[0]
    fig, ax = plt.subplots(figsize=(10, 3), facecolor="#0e1117")
    ax.set_facecolor("#0e1117")
    ax.plot(selected_row["raw_closes"], color="#00ffb3", linewidth=1.5)
    ax.set_title(f"Grafic Curs: {selected_symbol} ({tf_str})", color="white")
    ax.tick_params(colors="white")
    ax.grid(True, color="#262730", linestyle="--")
    st.pyplot(fig)
