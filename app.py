import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Crypto Scanner", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def human_num(x):
    if x is None: return ""
    try: v = float(x)
    except: return ""
    av = abs(v)
    if av >= 1e9: return f"${v/1e9:.2f}B"
    if av >= 1e6: return f"${v/1e6:.2f}M"
    if av >= 1e3: return f"${v/1e3:.2f}K"
    return f"${v:.2f}"

@st.cache_data(ttl=60, show_spinner=False)
def fetch_coingecko_market():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h"
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = []
            for item in data:
                symbol = str(item.get("symbol", "")).upper() + "USDT"
                price = item.get("current_price")
                vol = item.get("total_volume")
                chg = item.get("price_change_percentage_24h")
                results.append({
                    "Symbol": symbol,
                    "Price": price,
                    "Vol 24H ($)": vol,
                    "Δ 24H (%)": chg
                })
            return pd.DataFrame(results)
    except Exception as e:
        pass
    return pd.DataFrame()

# --- INTERFAȚĂ STREMLIT ---
st.title("🚀 Real-Time Crypto Futures & Market Scanner")

col1, col2 = st.columns([4, 2])
with col1:
    st.write("Sursa date: Market Aggregator API (Bypass Cloudflare / Block limits)")
with col2:
    if st.button("🔄 Actualizează Datele"):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Preluare date de piață..."):
    df = fetch_coingecko_market()

if df.empty:
    st.error("⚠️ Serverul se reîncarcă. Te rugăm să apeși butonul 'Actualizează Datele' peste câteva secunde.")
else:
    st.subheader(f"Top {len(df)} Monede Crypto")
    
    top_option = st.radio("Sortează după:", ["Volume (24H)", "Gaineri (% 24H)", "Loseri (% 24H)"], horizontal=True)

    if top_option == "Volume (24H)":
        df = df.sort_values(by="Vol 24H ($)", ascending=False)
    elif top_option == "Gaineri (% 24H)":
        df = df.sort_values(by="Δ 24H (%)", ascending=False)
    elif top_option == "Loseri (% 24H)":
        df = df.sort_values(by="Δ 24H (%)", ascending=True)

    display_df = df.copy()
    display_df["Vol 24H ($)"] = display_df["Vol 24H ($)"].apply(human_num)
    display_df["Price"] = display_df["Price"].apply(lambda x: f"${x:.4f}" if x and x >= 1 else (f"${x:.7f}" if x else "-"))
    display_df["Δ 24H (%)"] = display_df["Δ 24H (%)"].apply(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "-")

    st.dataframe(display_df, use_container_width=True, height=600)
