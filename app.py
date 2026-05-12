"""
Commodity Intelligence Dashboard
Professional crude oil & commodities terminal
Sources: OilPriceAPI + Omkar Commodity API + Twelve Data + EIA + CFTC
Architecture: background thread pre-fetches all data, serves from memory cache
"""

import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import requests
import feedparser
import threading
import time
from datetime import datetime, timedelta
import os

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="Commodity Intelligence",
    update_title=None,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server

# ── Colours ───────────────────────────────────────────────────────────────────
C = {
    "bg":      "#0a0d14",
    "surface": "#111520",
    "card":    "#161b2e",
    "border":  "#1e2540",
    "accent":  "#3d6af5",
    "green":   "#1db37a",
    "red":     "#d94f4f",
    "amber":   "#e8a020",
    "teal":    "#18b8a8",
    "purple":  "#8a4fd6",
    "text":    "#dde2f5",
    "muted":   "#6b749a",
}

# ── API Config ────────────────────────────────────────────────────────────────
OIL_KEY   = "799133b15930b2ffdf9835f8e09c980b232eecab16be00f2956d91de1da5af98"
OIL_BASE  = "https://api.oilpriceapi.com/v1"
OIL_HDR   = {"Authorization": f"Token {OIL_KEY}", "Content-Type": "application/json"}

OMKAR_KEY  = "ok_b313ea3f8e792745ff032f07fbfe2348"
OMKAR_BASE = "https://commodity-price-api.omkar.cloud"

TD_KEY    = "d01faaa78c0b467f93d8b35dc09ee7fc"
TD_BASE   = "https://api.twelvedata.com"

EIA_KEY   = "GJf5HWhOHneOmzBuq0pwz1xWbSLwdgy63McZGJqY"
EIA_BASE  = "https://api.eia.gov/v2"

# ── Instrument definitions ────────────────────────────────────────────────────
# OilPriceAPI codes
OIL_CODES = {
    "Brent Crude":     "BRENT_CRUDE_USD",
    "WTI Crude":       "WTI_USD",
    "Dubai Crude":     "DUBAI_CRUDE_USD",
    "Urals Crude":     "URALS_CRUDE_USD",
    "WTI Midland":     "WTI_MIDLAND_USD",
    "OPEC Basket":     "OPEC_BASKET_USD",
    "Gasoline RBOB":   "GASOLINE_RBOB_USD",
    "ULSD Diesel":     "ULSD_DIESEL_USD",
    "Jet Fuel":        "JET_FUEL_USD",
    "Heating Oil":     "HEATING_OIL_USD",
    "Henry Hub Gas":   "NATURAL_GAS_USD",
    "Dutch TTF Gas":   "DUTCH_TTF_NATURAL_GAS_USD",
    "JKM LNG":         "JKM_LNG_USD",
    "VLSFO":           "VLSFO_USD",
    "HSFO 380":        "HFO_380_USD",
    "MGO":             "MGO_05S_USD",
}

# Omkar API names (fallback for oil prices + metals/ags)
OMKAR_NAMES = {
    "WTI Crude":       "crude_oil",
    "Brent Crude":     "brent_crude_oil",
    "Henry Hub Gas":   "natural_gas",
    "Gasoline RBOB":   "gasoline_rbob",
    "Heating Oil":     "heating_oil",
    "Gold":            "gold",
    "Silver":          "silver",
    "Copper":          "copper",
    "Corn":            "corn",
    "Wheat":           "wheat",
    "Soybeans":        "soybean",
}

# Twelve Data symbols
TD_SYMS = {
    "S&P 500":         "SPX",
    "XLE Energy ETF":  "XLE",
    "XOP Oil & Gas":   "XOP",
    "ExxonMobil":      "XOM",
    "Shell":           "SHEL",
    "BP":              "BP",
    "TotalEnergies":   "TTE",
    "Valero":          "VLO",
    "Marathon Pete":   "MPC",
    "Euronav VLCC":    "EURN",
    "DHT Holdings":    "DHT",
    "Frontline":       "FRO",
    "Flex LNG":        "FLNG",
    "Golar LNG":       "GLNG",
    "BDRY Dry Bulk":   "BDRY",
    "Gold":            "XAU/USD",
    "Copper":          "XCU/USD",
    "DXY":             "DXY",
    "US 10Y Yield":    "TNX",
    "VIX":             "VIX",
    "EUR/USD":         "EUR/USD",
    "USD/CNY":         "USD/CNY",
}

NEWS_FEEDS = [
    ("Reuters",  "https://feeds.reuters.com/reuters/businessNews"),
    ("EIA",      "https://www.eia.gov/rss/news.xml"),
    ("FT",       "https://www.ft.com/commodities?format=rss"),
    ("Platts",   "https://www.spglobal.com/commodityinsights/en/rss-feed/oil"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY CACHE — all data lives here, served instantly to UI
# ═══════════════════════════════════════════════════════════════════════════════

_cache = {
    "prices":    {},      # {name: {price, chg, pct}}
    "history":   {},      # {name: DataFrame}
    "eia":       {},      # {series_id: DataFrame}
    "cot":       pd.DataFrame(),
    "news":      [],
    "last_full": None,    # datetime of last full refresh
    "status":    "Initialising...",
}
_cache_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════════════

def _oil_price(code: str) -> float | None:
    try:
        r = requests.get(f"{OIL_BASE}/prices/latest",
                         params={"by_code": code}, headers=OIL_HDR, timeout=8)
        d = r.json()
        if d.get("status") == "success":
            return float(d["data"]["price"])
    except Exception:
        pass
    return None


def _omkar_price(name: str) -> float | None:
    try:
        r = requests.get(f"{OMKAR_BASE}/commodity-price",
                         params={"name": name},
                         headers={"API-Key": OMKAR_KEY}, timeout=8)
        d = r.json()
        return float(d.get("price_usd") or 0) or None
    except Exception:
        pass
    return None


def _td_batch(syms: list[str]) -> dict:
    """Fetch multiple TD quotes in one call."""
    try:
        r = requests.get(f"{TD_BASE}/batch_price_quote",
                         params={"symbol": ",".join(syms), "apikey": TD_KEY},
                         timeout=15)
        d = r.json()
        if isinstance(d, list):
            return {item["symbol"]: item for item in d}
        elif isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _oil_history(code: str, days: int = 365) -> pd.DataFrame:
    try:
        end   = datetime.utcnow()
        start = end - timedelta(days=days)
        r = requests.get(f"{OIL_BASE}/prices", headers=OIL_HDR, params={
            "by_code":  code,
            "by_period": "daily",
            "start_at": start.strftime("%Y-%m-%dT00:00:00Z"),
            "end_at":   end.strftime("%Y-%m-%dT23:59:59Z"),
        }, timeout=20)
        d   = r.json()
        pts = d.get("data", [])
        if not pts:
            return pd.DataFrame()
        df = pd.DataFrame(pts)
        df["date"]  = pd.to_datetime(df["created_at"]).dt.normalize()
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.groupby("date")["price"].last().reset_index()
        return df.set_index("date").sort_index().dropna()
    except Exception:
        return pd.DataFrame()


def _td_history(sym: str, days: int = 365) -> pd.DataFrame:
    try:
        end   = datetime.utcnow()
        start = end - timedelta(days=days)
        r = requests.get(f"{TD_BASE}/time_series", params={
            "symbol":     sym,
            "interval":   "1day",
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date":   end.strftime("%Y-%m-%d"),
            "outputsize": min(days, 5000),
            "apikey":     TD_KEY,
        }, timeout=20)
        d    = r.json()
        vals = d.get("values", [])
        if not vals:
            return pd.DataFrame()
        df = pd.DataFrame(vals)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df["price"]    = pd.to_numeric(df["close"], errors="coerce")
        return df.set_index("datetime").sort_index()[["price"]].dropna()
    except Exception:
        return pd.DataFrame()


def _fetch_eia(series_id: str, length: int = 104) -> pd.DataFrame:
    try:
        r = requests.get(
            f"{EIA_BASE}/petroleum/stoc/wstk/data/",
            params={
                "api_key":         EIA_KEY,
                "frequency":       "weekly",
                "data[0]":         "value",
                f"facets[series][]": series_id,
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length":          length,
            }, timeout=10)
        d    = r.json()
        rows = d.get("response", {}).get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)[["period", "value"]].copy()
        df["period"] = pd.to_datetime(df["period"])
        df["value"]  = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna().sort_values("period")
    except Exception:
        return pd.DataFrame()


def _fetch_cot() -> pd.DataFrame:
    try:
        r = requests.get(
            "https://publicreporting.cftc.gov/resource/jun7-fc8e.json",
            params={
                "commodity_name": "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
                "$order":         "report_date_as_yyyy_mm_dd DESC",
                "$limit":         "52",
            }, timeout=10)
        rows = r.json()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"]   = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
        df["longs"]  = pd.to_numeric(df.get("m_money_positions_long_all",  0), errors="coerce")
        df["shorts"] = pd.to_numeric(df.get("m_money_positions_short_all", 0), errors="coerce")
        df["net"]    = df["longs"] - df["shorts"]
        return df.sort_values("date")
    except Exception:
        return pd.DataFrame()


def _fetch_news() -> list:
    articles = []
    for source, url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                articles.append({
                    "source": source,
                    "title":  e.get("title", ""),
                    "link":   e.get("link",  "#"),
                    "time":   e.get("published", "")[:25],
                })
        except Exception:
            pass
    return articles[:24]


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND REFRESH THREAD
# ═══════════════════════════════════════════════════════════════════════════════

def _refresh_prices():
    """Fetch all current prices."""
    prices = {}

    # Oil prices via OilPriceAPI
    for name, code in OIL_CODES.items():
        p = _oil_price(code)
        if p:
            prices[name] = {"price": p, "chg": 0.0, "pct": 0.0}

    # Fill missing oil prices via Omkar
    for name, omk in OMKAR_NAMES.items():
        if name not in prices:
            p = _omkar_price(omk)
            if p:
                prices[name] = {"price": p, "chg": 0.0, "pct": 0.0}

    # Equities + macro via Twelve Data batch
    td_syms = list(TD_SYMS.values())
    quotes  = _td_batch(td_syms)
    for name, sym in TD_SYMS.items():
        q = quotes.get(sym, {})
        if not q or "code" in q:
            continue
        try:
            price = float(q.get("close") or q.get("price") or 0)
            prev  = float(q.get("previous_close") or price)
            chg   = price - prev
            pct   = (chg / prev * 100) if prev else 0
            prices[name] = {"price": price, "chg": chg, "pct": pct}
        except Exception:
            continue

    return prices


def _refresh_history():
    """Fetch price history for key instruments."""
    history = {}

    # Key oil histories via OilPriceAPI
    oil_hist = {
        "Brent Crude":   "BRENT_CRUDE_USD",
        "WTI Crude":     "WTI_USD",
        "Dubai Crude":   "DUBAI_CRUDE_USD",
        "Urals Crude":   "URALS_CRUDE_USD",
        "Henry Hub Gas": "NATURAL_GAS_USD",
        "Dutch TTF Gas": "DUTCH_TTF_NATURAL_GAS_USD",
        "JKM LNG":       "JKM_LNG_USD",
        "Gasoline RBOB": "GASOLINE_RBOB_USD",
        "ULSD Diesel":   "ULSD_DIESEL_USD",
        "Jet Fuel":      "JET_FUEL_USD",
        "VLSFO":         "VLSFO_USD",
        "HSFO 380":      "HFO_380_USD",
    }
    for name, code in oil_hist.items():
        df = _oil_history(code, 365)
        if not df.empty:
            history[name] = df

    # Equity histories via Twelve Data
    td_hist = {
        "XLE Energy ETF": "XLE",
        "DXY":            "DXY",
        "Gold":           "XAU/USD",
        "Copper":         "XCU/USD",
        "VIX":            "VIX",
        "US 10Y Yield":   "TNX",
        "Euronav VLCC":   "EURN",
        "Frontline":      "FRO",
        "BDRY Dry Bulk":  "BDRY",
        "Flex LNG":       "FLNG",
        "XOP Oil & Gas":  "XOP",
    }
    for name, sym in td_hist.items():
        df = _td_history(sym, 365)
        if not df.empty:
            history[name] = df

    return history


def _refresh_eia():
    """Fetch all EIA series."""
    series = {
        "crude":      "WCRSTUS1",
        "cushing":    "WCSSTUS1",
        "gasoline":   "WGTSTUS1",
        "distillate": "WDISTUS1",
        "refutil":    "WPULEUS3",
    }
    eia = {}
    for key, sid in series.items():
        df = _fetch_eia(sid, 104)
        if not df.empty:
            eia[key] = df
    return eia


def full_refresh():
    """Full data refresh — runs in background thread."""
    global _cache
    with _cache_lock:
        _cache["status"] = "Refreshing prices..."

    prices  = _refresh_prices()
    history = _refresh_history()
    eia     = _refresh_eia()
    cot     = _fetch_cot()
    news    = _fetch_news()

    with _cache_lock:
        _cache["prices"]    = prices
        _cache["history"]   = history
        _cache["eia"]       = eia
        _cache["cot"]       = cot
        _cache["news"]      = news
        _cache["last_full"] = datetime.utcnow()
        _cache["status"]    = "Live"


def prices_only_refresh():
    """Quick price-only refresh — runs every 5 minutes."""
    prices = _refresh_prices()
    with _cache_lock:
        _cache["prices"] = prices
        _cache["last_full"] = datetime.utcnow()
        _cache["status"] = "Live"


def background_loop():
    """Background thread: full refresh on start, then prices every 5 min,
    full refresh every hour."""
    full_refresh()
    last_full = time.time()
    while True:
        time.sleep(300)  # 5 minutes
        if time.time() - last_full > 3600:
            full_refresh()
            last_full = time.time()
        else:
            prices_only_refresh()


# Start background thread immediately
_bg_thread = threading.Thread(target=background_loop, daemon=True)
_bg_thread.start()


# ═══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def sec(title: str, sub: str = "") -> html.Div:
    return html.Div([
        html.Div(title, style={"fontSize": "13px", "fontWeight": "700",
                                "color": C["text"], "margin": "0 0 2px 0",
                                "letterSpacing": "0.5px"}),
        html.Div(sub, style={"color": C["muted"], "fontSize": "11px"}),
    ], style={"borderLeft": f"3px solid {C['accent']}", "paddingLeft": "10px",
              "marginBottom": "14px", "marginTop": "8px"})


def pcard(name: str, d: dict) -> dbc.Col:
    up  = d.get("pct", 0) >= 0
    col = C["green"] if up else C["red"]
    arr = "+" if up else ""
    p   = d.get("price", 0)
    pct = d.get("pct", 0)
    chg = d.get("chg", 0)
    fmt = f"{p:,.3f}" if p < 10 else f"{p:,.2f}" if p < 1000 else f"{p:,.1f}"
    return dbc.Col(html.Div([
        html.Div(name, style={"fontSize": "10px", "color": C["muted"],
                               "marginBottom": "4px", "fontWeight": "500",
                               "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div(fmt, style={"fontSize": "19px", "color": C["text"],
                              "fontWeight": "600", "fontVariantNumeric": "tabular-nums"}),
        html.Div(f"{arr}{pct:.2f}%  {chg:+.2f}" if chg else f"{arr}{pct:.2f}%",
                 style={"fontSize": "11px", "color": col, "marginTop": "2px"}),
    ], style={
        "background": C["card"],
        "border": f"1px solid {C['border']}",
        "borderTop": f"2px solid {col}",
        "borderRadius": "6px",
        "padding": "10px 12px",
    }),
    xs=6, sm=4, md=3, lg=2, style={"marginBottom": "8px", "paddingRight": "6px", "paddingLeft": "6px"})


def ecard(name: str) -> dbc.Col:
    return dbc.Col(html.Div([
        html.Div(name, style={"fontSize": "10px", "color": C["muted"],
                               "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div("—", style={"fontSize": "19px", "color": C["muted"], "marginTop": "4px"}),
        html.Div("loading", style={"fontSize": "11px", "color": C["muted"]}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "6px", "padding": "10px 12px"}),
    xs=6, sm=4, md=3, lg=2, style={"marginBottom": "8px", "paddingRight": "6px", "paddingLeft": "6px"})


def price_strip(names: list, prices: dict) -> dbc.Row:
    cards = [pcard(n, prices[n]) if n in prices else ecard(n) for n in names]
    return dbc.Row(cards, style={"marginBottom": "16px", "marginLeft": "-6px", "marginRight": "-6px"})


def spread_box(label: str, val, unit: str = "", note: str = "",
               bullish_if_positive: bool = True) -> dbc.Col:
    if val is None or val == 0:
        col  = C["muted"]
        disp = "—"
        sign = ""
    else:
        col  = C["green"] if (val > 0) == bullish_if_positive else C["red"]
        sign = "+" if val > 0 else ""
        disp = f"{sign}{val:.2f} {unit}"
    return dbc.Col(html.Div([
        html.Div(label, style={"fontSize": "10px", "color": C["muted"],
                                "textTransform": "uppercase", "letterSpacing": "0.5px",
                                "marginBottom": "4px"}),
        html.Div(disp, style={"fontSize": "17px", "fontWeight": "600", "color": col}),
        html.Div(note, style={"fontSize": "10px", "color": C["muted"], "marginTop": "3px"}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderLeft": f"3px solid {col}", "borderRadius": "6px",
              "padding": "10px 12px"}),
    md=3, style={"marginBottom": "8px"})


def hist_chart(name: str, title: str, color: str, days: int = 365,
               height: int = 200) -> go.Figure:
    with _cache_lock:
        df = _cache["history"].get(name, pd.DataFrame())
    fig = go.Figure()
    if not df.empty:
        df2  = df.tail(days)
        vals = df2["price"].values.flatten()
        fig.add_trace(go.Scatter(
            x=df2.index, y=vals, mode="lines",
            line=dict(color=color, width=1.6),
            fill="tozeroy", fillcolor=color + "0f",
            hovertemplate="%{y:.2f}<extra></extra>",
        ))
        # Add 200-day MA if enough data
        if len(df2) >= 50:
            ma = df2["price"].rolling(50).mean()
            fig.add_trace(go.Scatter(
                x=df2.index, y=ma.values.flatten(),
                mode="lines", line=dict(color=C["muted"], width=1, dash="dot"),
                name="50d MA", hovertemplate="50d MA: %{y:.2f}<extra></extra>",
            ))
    else:
        fig.add_annotation(text="Fetching data...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"], size=11))
    fig.update_layout(
        title=dict(text=title, font=dict(size=11, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=4, r=4, t=26, b=4),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=8)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=8)),
        height=height, showlegend=False,
    )
    return fig


def spread_hist_chart(name_a: str, name_b: str, title: str,
                      mult_a: float = 1.0, mult_b: float = 1.0) -> go.Figure:
    fig = go.Figure()
    with _cache_lock:
        a = _cache["history"].get(name_a, pd.DataFrame())
        b = _cache["history"].get(name_b, pd.DataFrame())
    try:
        if a.empty or b.empty:
            raise ValueError()
        df = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
        df["spread"] = df["price_a"] * mult_a - df["price_b"] * mult_b
        vals = df["spread"].values.flatten()
        avg  = float(df["spread"].mean())
        hi   = float(df["spread"].quantile(0.9))
        lo   = float(df["spread"].quantile(0.1))
        col  = C["green"] if float(vals[-1]) > avg else C["red"]
        fig.add_trace(go.Scatter(
            x=df.index, y=vals, mode="lines",
            line=dict(color=col, width=1.6),
            fill="tozeroy", fillcolor=col + "0f",
            hovertemplate="%{y:.2f}<extra></extra>",
        ))
        fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"],
                      opacity=0.5, annotation_text=f"avg {avg:.2f}",
                      annotation_font_color=C["amber"], annotation_font_size=8)
        latest = float(vals[-1])
        pctile = int((latest - lo) / (hi - lo) * 100) if hi != lo else 50
        fig.add_annotation(
            text=f"{latest:.2f}  |  {pctile}th pctile",
            x=0.98, y=0.94, xref="paper", yref="paper",
            showarrow=False,
            font=dict(color=C["green"] if latest > avg else C["red"], size=9))
    except Exception:
        fig.add_annotation(text="Fetching data...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"], size=11))
    fig.update_layout(
        title=dict(text=title, font=dict(size=11, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=4, r=4, t=26, b=4),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=8)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=8)),
        height=200, showlegend=False,
    )
    return fig


def eia_fig(key: str, title: str) -> go.Figure:
    with _cache_lock:
        df = _cache["eia"].get(key, pd.DataFrame())
    fig = go.Figure()
    if not df.empty:
        d52  = df.tail(52)
        avg  = float(df["value"].mean())
        lat  = float(d52["value"].iloc[-1])
        col  = C["red"] if lat > avg else C["green"]
        fig.add_trace(go.Scatter(
            x=d52["period"], y=d52["value"].values.flatten(),
            mode="lines", line=dict(color=col, width=2),
            hovertemplate="%{x|%b %d}: %{y:,.0f}<extra></extra>",
        ))
        fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"],
                      opacity=0.5, annotation_text=f"2yr avg",
                      annotation_font_color=C["amber"], annotation_font_size=8)
        diff = lat - avg
        fig.add_annotation(
            text=f"vs avg: {'+' if diff>=0 else ''}{diff:,.0f}k",
            x=0.98, y=0.94, xref="paper", yref="paper",
            showarrow=False, font=dict(color=col, size=9))
    else:
        fig.add_annotation(text="Fetching EIA data...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"], size=11))
    fig.update_layout(
        title=dict(text=title, font=dict(size=11, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=4, r=4, t=26, b=4),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=8)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=8)),
        height=200,
    )
    return fig


def ibox(title: str, body: str, color: str = None) -> html.Div:
    color = color or C["accent"]
    return html.Div([
        html.Div(title, style={"fontSize": "11px", "fontWeight": "700",
                                "color": color, "marginBottom": "5px",
                                "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div(body,  style={"fontSize": "12px", "color": C["text"],
                                "lineHeight": "1.6"}),
    ], style={"background": C["card"], "border": f"1px solid {color}22",
              "borderLeft": f"3px solid {color}", "borderRadius": "6px",
              "padding": "10px 14px", "marginBottom": "8px"})


def news_card(a: dict) -> html.Div:
    return html.Div([
        html.Div(a["source"], style={"fontSize": "10px", "color": C["accent"],
                                      "fontWeight": "600", "marginBottom": "3px",
                                      "textTransform": "uppercase"}),
        html.A(a["title"], href=a["link"], target="_blank", style={
            "color": C["text"], "fontSize": "12px",
            "textDecoration": "none", "display": "block", "lineHeight": "1.45"}),
        html.Div(a.get("time", ""), style={"fontSize": "10px",
                                            "color": C["muted"], "marginTop": "3px"}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "6px", "padding": "10px 12px", "marginBottom": "8px"})


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

TS = {"color": C["muted"], "backgroundColor": "transparent", "border": "none",
      "padding": "12px 16px", "fontSize": "12px", "fontWeight": "500"}
TS_SEL = {**TS, "color": C["accent"],
          "borderBottom": f"2px solid {C['accent']}", "fontWeight": "700"}

app.layout = html.Div(
    style={"background": C["bg"], "minHeight": "100vh",
           "fontFamily": "'Inter','Segoe UI',sans-serif"},
    children=[
        # Header
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Span("COMMODITY INTELLIGENCE", style={
                        "color": C["text"], "fontSize": "13px",
                        "fontWeight": "800", "letterSpacing": "3px"}),
                ], width="auto"),
                dbc.Col(html.Div(id="status-bar",
                                 style={"color": C["muted"], "fontSize": "11px",
                                        "textAlign": "right", "paddingTop": "3px"})),
                dbc.Col(dbc.Button("Refresh", id="refresh-btn", size="sm", style={
                    "background": "transparent",
                    "border": f"1px solid {C['border']}",
                    "color": C["muted"], "fontSize": "11px",
                    "borderRadius": "4px", "padding": "3px 10px",
                }), width="auto"),
            ], align="center", style={"padding": "10px 0"}),
        ], style={"background": C["surface"], "borderBottom": f"1px solid {C['border']}",
                  "padding": "0 20px", "position": "sticky", "top": "0", "zIndex": "100"}),

        # Tabs
        dcc.Tabs(id="tabs", value="crude",
                 style={"background": C["surface"],
                        "borderBottom": f"1px solid {C['border']}"},
                 children=[
            dcc.Tab(label="Crude Oil",       value="crude",    style=TS, selected_style=TS_SEL),
            dcc.Tab(label="Products",        value="products", style=TS, selected_style=TS_SEL),
            dcc.Tab(label="Gas & LNG",       value="gas",      style=TS, selected_style=TS_SEL),
            dcc.Tab(label="Freight",         value="freight",  style=TS, selected_style=TS_SEL),
            dcc.Tab(label="Macro & Metals",  value="macro",    style=TS, selected_style=TS_SEL),
            dcc.Tab(label="Positioning",     value="position", style=TS, selected_style=TS_SEL),
            dcc.Tab(label="News",            value="news",     style=TS, selected_style=TS_SEL),
        ]),

        html.Div(id="content", style={"padding": "18px 20px"}),

        # Poll every 60 seconds to update status bar and prices
        dcc.Interval(id="poll", interval=60_000, n_intervals=0),
        dcc.Store(id="tick"),
    ]
)


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("tick", "data"),
    Output("status-bar", "children"),
    Input("poll", "n_intervals"),
    Input("refresh-btn", "n_clicks"),
)
def tick(_, clicks):
    """Trigger manual refresh if button clicked, update status bar."""
    if clicks:
        threading.Thread(target=prices_only_refresh, daemon=True).start()
    with _cache_lock:
        st  = _cache["status"]
        ts  = _cache["last_full"]
    ts_str = ts.strftime("%H:%M UTC") if ts else "initialising..."
    return str(datetime.utcnow()), f"{st}  |  {ts_str}"


@app.callback(
    Output("content", "children"),
    Input("tabs", "value"),
    Input("tick", "data"),
)
def render(tab, _):
    with _cache_lock:
        prices  = dict(_cache["prices"])
        history = dict(_cache["history"])
        eia     = dict(_cache["eia"])
        cot_df  = _cache["cot"].copy() if not _cache["cot"].empty else pd.DataFrame()
        news    = list(_cache["news"])

    # ── CRUDE OIL ─────────────────────────────────────────────────────────────
    if tab == "crude":
        crude_names = ["Brent Crude", "WTI Crude", "Dubai Crude",
                       "Urals Crude", "WTI Midland", "OPEC Basket"]

        brent = prices.get("Brent Crude",  {}).get("price", 0)
        wti   = prices.get("WTI Crude",    {}).get("price", 0)
        dubai = prices.get("Dubai Crude",  {}).get("price", 0)
        urals = prices.get("Urals Crude",  {}).get("price", 0)

        spread_row = dbc.Row([
            spread_box("Brent – WTI", round(brent - wti, 2) if brent and wti else None,
                       "$/bbl", "Atlantic arb / US export driver"),
            spread_box("Brent – Dubai", round(brent - dubai, 2) if brent and dubai else None,
                       "$/bbl", "East/west routing signal (EFS proxy)"),
            spread_box("Urals discount", round(urals - brent, 2) if brent and urals else None,
                       "$/bbl", "Russian sanctions discount", bullish_if_positive=False),
            dbc.Col(html.Div([
                html.Div("OPEC+ spare capacity", style={"fontSize":"10px","color":C["muted"],
                          "textTransform":"uppercase","letterSpacing":"0.5px","marginBottom":"4px"}),
                html.Div("~3mb/d est.", style={"fontSize":"17px","fontWeight":"600","color":C["amber"]}),
                html.Div("Low spare = high geopolitical premium",
                         style={"fontSize":"10px","color":C["muted"],"marginTop":"3px"}),
            ], style={"background":C["card"],"border":f"1px solid {C['border']}",
                      "borderLeft":f"3px solid {C['amber']}","borderRadius":"6px",
                      "padding":"10px 12px"}), md=3, style={"marginBottom":"8px"}),
        ], style={"marginBottom":"16px"})

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=hist_chart("Brent Crude","Brent Crude 1yr",C["accent"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=hist_chart("WTI Crude","WTI Crude 1yr",C["teal"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=spread_hist_chart("Brent Crude","WTI Crude","Brent – WTI spread $/bbl"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=spread_hist_chart("Brent Crude","Dubai Crude","Brent – Dubai spread $/bbl"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"16px"})

        inv_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=eia_fig("crude",   "US Crude Stocks (k bbls)"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=eia_fig("cushing", "Cushing OK Stocks (k bbls)"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"16px"})

        context = dbc.Row([
            dbc.Col([
                ibox("OPEC+ Mechanics",
                     "Voluntary cuts ~3.66mb/d above 2022 baseline. Watch monthly production vs quota — "
                     "Iraq, UAE and Kazakhstan historically over-produce their allocations. "
                     "Any unwind of cuts is immediately bearish. Compliance data ~2 weeks after month-end.", C["amber"]),
                ibox("US Shale",
                     "Production ~13.5mb/d. Responds to price with 3-6 month lag (rig count → DUC → first oil). "
                     "Permian basin drives marginal growth. Baker Hughes rig count every Friday = "
                     "leading indicator for supply 6 months out. Watch DUC inventory for near-term signal.", C["teal"]),
                ibox("Russia Post-Sanctions",
                     "Official production ~9.2mb/d. Urals rerouted to India and China at deep discount to Brent. "
                     "Shadow fleet (~600 vessels) carries this flow — absorbs global tanker capacity. "
                     "Discount compression = less incentive for Asian buyers = bearish for Russian barrels.", C["purple"]),
            ], md=6),
            dbc.Col([
                ibox("China Demand Signals",
                     "~16mb/d — world's largest crude importer. Key signals: customs data (monthly crude imports), "
                     "Shandong teapot refinery runs, SPR build/draw cycles, product export volumes. "
                     "EV penetration now ~35% of new car sales — structural headwind for gasoline demand.", C["green"]),
                ibox("How Dated Brent is Set",
                     "Physical price assessed in the Platts Price Window, 4:00-4:30pm London. "
                     "BFOET basket: Brent, Forties, Oseberg, Ekofisk, Troll. "
                     "Forties usually cheapest and price-setting (the marginal barrel). "
                     "Physical tightness here flows directly into the paper futures market.", C["accent"]),
                ibox("Geopolitical Risk Premium",
                     "Strait of Hormuz carries ~20% of global oil. Current EIA forecast: "
                     "Brent peaking ~$115/b Q2 2026 on Gulf production disruption risk. "
                     "Upside options skew (25d risk reversal) is the market-implied premium — "
                     "watch this vs realised vol for cheap/expensive hedges.", C["red"]),
            ], md=6),
        ])

        return html.Div([
            sec("Crude Oil", "Global grades — Brent, WTI, Dubai, Urals, Midland, OPEC basket"),
            price_strip(crude_names, prices),
            sec("Key Spreads", "Live calculated from prices above"),
            spread_row,
            sec("Price History — 1yr with 50d MA", ""),
            charts,
            sec("EIA Weekly Inventories", "Wednesday 10:30am ET — most market-moving weekly data release in oil"),
            inv_row,
            sec("Fundamental Context", ""),
            context,
        ])

    # ── PRODUCTS ──────────────────────────────────────────────────────────────
    elif tab == "products":
        prod_names = ["Gasoline RBOB", "ULSD Diesel", "Jet Fuel",
                      "Heating Oil", "VLSFO", "HSFO 380", "MGO"]

        brent = prices.get("Brent Crude", {}).get("price", 0)
        wti   = prices.get("WTI Crude",   {}).get("price", 0)
        gas   = prices.get("Gasoline RBOB",{}).get("price", 0)
        ulsd  = prices.get("ULSD Diesel", {}).get("price", 0)
        jet   = prices.get("Jet Fuel",    {}).get("price", 0)
        vlsfo = prices.get("VLSFO",       {}).get("price", 0)
        hsfo  = prices.get("HSFO 380",    {}).get("price", 0)

        # Crack spreads (products in $/bbl vs Brent)
        spread_row = dbc.Row([
            spread_box("Gasoline crack",
                       round(gas * 42 - brent, 2) if gas and brent else None,
                       "$/bbl", "RBOB vs Brent"),
            spread_box("Diesel crack",
                       round(ulsd * 42 - brent, 2) if ulsd and brent else None,
                       "$/bbl", "ULSD vs Brent"),
            spread_box("Jet crack",
                       round(jet * 42 - brent, 2) if jet and brent else None,
                       "$/bbl", "Jet fuel vs Brent"),
            spread_box("Hi-5 spread",
                       round(vlsfo - hsfo, 2) if vlsfo and hsfo else None,
                       "$/t", "VLSFO vs HSFO 380 — IMO 2020 signal"),
        ], style={"marginBottom":"16px"})

        inv_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=eia_fig("gasoline",   "US Gasoline Stocks (k bbls)"),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=eia_fig("distillate", "US Distillate Stocks (k bbls)"),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=eia_fig("refutil",    "US Refinery Utilisation (%)"),
                              config={"displayModeBar":False}), md=4),
        ], style={"marginBottom":"16px"})

        crack_charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=spread_hist_chart("Gasoline RBOB","Brent Crude",
                              "Gasoline crack vs Brent ($/bbl)", mult_a=42.0),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=spread_hist_chart("ULSD Diesel","Brent Crude",
                              "Diesel crack vs Brent ($/bbl)", mult_a=42.0),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=hist_chart("VLSFO","VLSFO — bunker fuel 1yr",C["teal"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=spread_hist_chart("VLSFO","HSFO 380","Hi-5 spread — VLSFO vs HSFO"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"16px"})

        context = dbc.Row([
            dbc.Col([
                ibox("Reading Crack Spreads",
                     "Crack spread = product price minus crude. Measures refinery profitability. "
                     "High cracks → refiners run harder → more crude demand → supportive for flat price. "
                     "3-2-1 crack = (2 × gasoline + 1 × diesel − 3 × crude) / 3. "
                     "Percentile vs 1yr range tells you if margins are historically wide or tight.", C["accent"]),
                ibox("Gasoline Seasonality",
                     "US driving season Memorial Day to Labor Day (May–Sept). "
                     "Gasoline crack typically peaks spring/summer. RVP spec switchover "
                     "in April/May tightens supply temporarily — watch Colonial Pipeline batching.", C["green"]),
            ], md=6),
            dbc.Col([
                ibox("Diesel — The Industrial Fuel",
                     "Diesel demand is the strongest signal for global industrial activity. "
                     "Heating oil peaks Q4/Q1. Jet fuel crack now strongest globally as aviation recovers. "
                     "Watch IATA monthly traffic data — leading indicator for jet demand.", C["amber"]),
                ibox("Marine Fuels — IMO 2020",
                     "IMO 2020 capped bunker sulphur at 0.5% (from 3.5%). Created structural VLSFO demand. "
                     "Hi-5 spread (VLSFO minus HSFO) reflects compliance cost for non-scrubber vessels. "
                     "Wide Hi-5 = bullish for complex refineries with hydrocracking capacity.", C["teal"]),
            ], md=6),
        ])

        return html.Div([
            sec("Refined Products & Marine Fuels",
                "Gasoline, diesel, jet fuel, heating oil, VLSFO, HSFO, MGO"),
            price_strip(prod_names, prices),
            sec("Live Crack Spreads", "Calculated from current prices"),
            spread_row,
            sec("EIA Product Inventories & Refinery Runs", ""),
            inv_row,
            sec("Crack Spread History — 1yr", ""),
            crack_charts,
            sec("Context", ""),
            context,
        ])

    # ── GAS & LNG ─────────────────────────────────────────────────────────────
    elif tab == "gas":
        gas_names = ["Henry Hub Gas", "Dutch TTF Gas", "JKM LNG",
                     "Flex LNG", "Golar LNG"]

        henry = prices.get("Henry Hub Gas",{}).get("price", 0)
        ttf   = prices.get("Dutch TTF Gas",{}).get("price", 0)
        jkm   = prices.get("JKM LNG",      {}).get("price", 0)

        spread_row = dbc.Row([
            spread_box("Henry Hub", henry, "$/MMBtu", "US gas benchmark"),
            spread_box("Dutch TTF", ttf,   "$/MMBtu", "European benchmark"),
            spread_box("JKM LNG",   jkm,   "$/MMBtu", "Asian LNG spot"),
            spread_box("TTF – Henry Hub",
                       round(ttf - henry, 2) if ttf and henry else None,
                       "$/MMBtu", "Transatlantic LNG arb signal"),
        ], style={"marginBottom":"16px"})

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=hist_chart("Henry Hub Gas","Henry Hub Gas 1yr",C["teal"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=hist_chart("Dutch TTF Gas","Dutch TTF Gas 1yr",C["accent"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=hist_chart("JKM LNG","JKM LNG 1yr",C["purple"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=spread_hist_chart("Dutch TTF Gas","Henry Hub Gas",
                              "TTF – Henry Hub spread"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"16px"})

        context = dbc.Row([
            dbc.Col([
                ibox("The LNG Routing Decision",
                     "US LNG goes east if JKM > Henry Hub + ~$3 liquefaction + freight. "
                     "Goes to Europe if TTF > JKM + freight. "
                     "This spread is calculated in real time by Vitol, Shell, Total on every cargo. "
                     "When TTF-JKM collapses, Atlantic cargoes divert to Asia.", C["teal"]),
                ibox("European Gas Storage",
                     "GIE AGSI data — % full vs seasonal norms. EU winter target ~90% full. "
                     "Summer injection season April–October. Storage deficit = TTF bullish. "
                     "Russia pipeline gas now minimal (NordStream offline). "
                     "Europe structurally dependent on Norwegian pipeline + LNG imports.", C["amber"]),
            ], md=6),
            dbc.Col([
                ibox("JKM Volatility",
                     "Asian LNG spot is the most volatile benchmark — can spike $3-5 in days. "
                     "Cold snap in NE Asia (Japan/Korea/China) triggers emergency buying. "
                     "Nuclear outages in Japan also drive spot demand. "
                     "Summer AC demand in China increasingly market-moving.", C["purple"]),
                ibox("US LNG Export Capacity",
                     "US now world's largest LNG exporter (~14 bcf/d). "
                     "Key terminals: Sabine Pass, Freeport, Corpus Christi, Cameron, Calcasieu. "
                     "Any outage removes supply and immediately spikes TTF and JKM. "
                     "New capacity (Plaquemines, Port Arthur) coming online 2025-2027.", C["green"]),
            ], md=6),
        ])

        return html.Div([
            sec("Natural Gas & LNG", "Henry Hub, Dutch TTF, JKM — the three global gas benchmarks"),
            price_strip(gas_names, prices),
            sec("Benchmark Comparison & Arb Signal", ""),
            spread_row,
            sec("Price History — 1yr", ""),
            charts,
            sec("Fundamental Context", ""),
            context,
        ])

    # ── FREIGHT ───────────────────────────────────────────────────────────────
    elif tab == "freight":
        freight_names = ["Euronav VLCC", "DHT Holdings", "Frontline",
                         "Flex LNG", "Golar LNG", "BDRY Dry Bulk"]

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=hist_chart("Euronav VLCC","Euronav — VLCC proxy",C["accent"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("Frontline","Frontline — crude tanker",C["teal"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("BDRY Dry Bulk","BDRY — Baltic Dry ETF",C["amber"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("Flex LNG","Flex LNG — LNG shipping",C["purple"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("DHT Holdings","DHT Holdings — VLCC",C["green"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("Golar LNG","Golar LNG — midstream",C["muted"]),
                              config={"displayModeBar":False}), md=4),
        ], style={"marginBottom":"16px"})

        routes = [
            ("TD3C — VLCC (ME Gulf to China)", C["accent"],
             "Benchmark crude tanker route, 2mb cargo, ~35 days voyage. "
             "Rates driven by OPEC+ export volumes and Chinese crude import demand. "
             "High Worldscale = tight tonnage = physical crude demand is strong. "
             "Euronav, DHT and Frontline are the best listed proxies."),
            ("TD20 — Suezmax (W.Africa to Europe)", C["teal"],
             "West Africa to NWE continent. Key route for Nigerian Bonny Light and Angolan Girassol "
             "into European refineries. Rates rise when Atlantic basin crude flows strongly westward. "
             "Also tracks US crude export flows to Europe via Aframax/Suezmax."),
            ("LNG Carriers", C["purple"],
             "Spot day rates range $40-180k/day depending on season. "
             "Spike sharply in winter when NE Asia drives spot demand. Low in summer shoulder season. "
             "Flex LNG and Golar LNG are listed proxies. "
             "TTF-JKM spread determines which direction cargoes flow."),
            ("Baltic Dry Index", C["amber"],
             "Dry bulk shipping: Capesize (iron ore, coal), Panamax (grain, coal), Supramax. "
             "BDI is a real-time barometer of global industrial demand — "
             "rising BDI signals Chinese steel production picking up. "
             "BDRY ETF tracks the index."),
            ("TC2 — MR Tanker (ARA to USAC)", C["green"],
             "Clean products tanker route, Amsterdam-Rotterdam-Antwerp to US Atlantic Coast. "
             "Tight TC2 rates signal strong transatlantic gasoline arbitrage flowing. "
             "Watches Colonial Pipeline batching schedule and ARA product stock levels."),
            ("Shadow Fleet", C["red"],
             "~600-700 vessels carrying Russian, Iranian and Venezuelan crude "
             "outside Western tracking and insurance frameworks. "
             "Absorbs global tanker capacity — when utilisation rises, mainstream freight tightens. "
             "Track via Kpler or Vortexa AIS data (professional tools)."),
        ]

        return html.Div([
            sec("Freight & Shipping", "Tanker rates, dry bulk, LNG shipping — listed equity proxies"),
            price_strip(freight_names, prices),
            sec("Shipping Equity Proxies — 1yr", ""),
            charts,
            sec("Key Routes & What They Signal", ""),
            dbc.Row([dbc.Col(ibox(t, b, c), md=6) for t, c, b in routes]),
        ])

    # ── MACRO & METALS ────────────────────────────────────────────────────────
    elif tab == "macro":
        macro_names = ["S&P 500","XLE Energy ETF","XOP Oil & Gas",
                       "ExxonMobil","Valero","Gold","Copper",
                       "DXY","US 10Y Yield","VIX","EUR/USD","USD/CNY"]

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=hist_chart("DXY","DXY USD Index",C["amber"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("Gold","Gold",C["amber"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("Copper","Copper",C["teal"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("US 10Y Yield","US 10Y Yield",C["red"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("VIX","VIX",C["purple"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=hist_chart("XLE Energy ETF","XLE Energy ETF",C["green"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=spread_hist_chart("Copper","Gold",
                              "Copper/Gold ratio (×100)", mult_a=100.0),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=hist_chart("XOP Oil & Gas","XOP Oil & Gas ETF",C["accent"]),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"16px"})

        context = dbc.Row([
            dbc.Col([
                ibox("DXY & Commodity Prices",
                     "Commodities priced in USD — strong dollar raises the cost for EM importers = demand destruction. "
                     "DXY and Brent have a strong negative correlation (typically -0.6 to -0.8). "
                     "Fed rate decisions are therefore directly commodity-relevant. "
                     "Watch real yields (TIPS) — negative real yields historically very bullish for hard assets.", C["amber"]),
                ibox("Copper as Global Demand Barometer",
                     "China consumes ~55% of global copper. Rising copper = China industrial activity picking up. "
                     "Copper-gold ratio rising = risk-on, growth expectations improving = bullish crude demand. "
                     "China Total Social Financing (credit data) leads copper by 6-9 months — "
                     "the best leading indicator for the complex.", C["teal"]),
            ], md=6),
            dbc.Col([
                ibox("Energy Equities vs Crude",
                     "XLE/XOP vs crude oil divergence signals market expectations. "
                     "Equities leading crude higher = forward-looking market expects crude to rise. "
                     "Equities lagging = equity market sceptical of the commodity move — watch for catch-up. "
                     "HY energy credit spreads give you the market's implied breakeven oil price.", C["green"]),
                ibox("VIX & Risk-Off Dynamics",
                     "High VIX = institutional deleveraging = all assets sold simultaneously. "
                     "In risk-off episodes, crude/commodity and equity correlations converge to 1. "
                     "After VIX spike and reversion, commodity vol often stays elevated — "
                     "historically a good entry point to buy back-month options cheaply.", C["purple"]),
            ], md=6),
        ])

        return html.Div([
            sec("Macro & Metals", "DXY, yields, VIX, copper, gold, energy equities"),
            price_strip(macro_names, prices),
            sec("Charts — 1yr with 50d MA", ""),
            charts,
            sec("Inter-Market Signals", ""),
            context,
        ])

    # ── POSITIONING ───────────────────────────────────────────────────────────
    elif tab == "position":
        fig_net   = go.Figure()
        fig_gross = go.Figure()
        signal_txt = "Loading CFTC data..."
        signal_col = C["muted"]
        latest_net = 0
        net_pct    = 50

        if not cot_df.empty:
            net    = cot_df["net"]
            longs  = cot_df["longs"]
            shorts = cot_df["shorts"]
            dates  = cot_df["date"]
            net_max    = float(net.max())
            net_min    = float(net.min())
            latest_net = int(net.iloc[-1])
            net_pct    = int((net.iloc[-1] - net_min) / (net_max - net_min) * 100) if net_max != net_min else 50

            colors = [C["green"] if v >= 0 else C["red"] for v in net]
            fig_net.add_trace(go.Bar(x=dates, y=net, marker_color=colors,
                hovertemplate="%{x|%b %d}: %{y:,.0f} contracts<extra></extra>"))
            fig_net.add_hrect(y0=net_max*0.85, y1=net_max,
                              fillcolor=C["red"], opacity=0.06,
                              annotation_text="Crowded long",
                              annotation_font_color=C["red"], annotation_font_size=9)
            fig_net.add_hrect(y0=net_min, y1=net_min*0.85,
                              fillcolor=C["green"], opacity=0.06,
                              annotation_text="Crowded short",
                              annotation_font_color=C["green"], annotation_font_size=9)

            fig_gross.add_trace(go.Scatter(x=dates, y=longs.values.flatten(),
                mode="lines", name="Longs", line=dict(color=C["green"], width=1.6)))
            fig_gross.add_trace(go.Scatter(x=dates, y=shorts.values.flatten(),
                mode="lines", name="Shorts", line=dict(color=C["red"], width=1.6)))

            signal_col = C["red"] if net_pct > 75 else C["green"] if net_pct < 25 else C["amber"]
            signal_txt = ("Crowded long — reversal risk high"   if net_pct > 75 else
                          "Crowded short — squeeze risk high"    if net_pct < 25 else
                          "Positioning neutral — no crowding signal")

        for fig, title in [
            (fig_net,   "WTI Crude — Managed Money Net Position (contracts)"),
            (fig_gross, "WTI Crude — Gross Longs vs Shorts"),
        ]:
            fig.update_layout(
                title=dict(text=title, font=dict(size=11, color=C["text"]), x=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=4, r=4, t=26, b=4),
                xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=8)),
                yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                           tickfont=dict(size=8)),
                legend=dict(font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
                height=260,
            )

        signal_card = html.Div([
            html.Div(signal_txt, style={"fontSize":"14px","fontWeight":"700","color":signal_col}),
            html.Div(f"Net: {latest_net:+,} contracts  |  {net_pct}th percentile vs 1yr range",
                     style={"fontSize":"11px","color":C["muted"],"marginTop":"5px"}),
        ], style={"background":C["card"],"border":f"1px solid {signal_col}33",
                  "borderLeft":f"3px solid {signal_col}","borderRadius":"6px",
                  "padding":"12px 16px","marginBottom":"16px"})

        return html.Div([
            sec("COT Positioning", "CFTC Commitment of Traders — managed money in WTI crude futures"),
            signal_card,
            dbc.Row([
                dbc.Col(dcc.Graph(figure=fig_net,   config={"displayModeBar":False}), md=6),
                dbc.Col(dcc.Graph(figure=fig_gross, config={"displayModeBar":False}), md=6),
            ], style={"marginBottom":"16px"}),
            dbc.Row([
                dbc.Col(ibox("How to Use the COT Report",
                    "CFTC Commitment of Traders released every Friday after close. "
                    "Managed money = hedge funds and CTAs. "
                    "Extreme net long = crowded trade = high reversal risk on any negative catalyst. "
                    "Extreme net short = short squeeze potential. "
                    "Use as a crowding risk indicator, not a standalone directional signal.", C["accent"]), md=6),
                dbc.Col(ibox("Commercials — The Smart Money Signal",
                    "Producers and refiners are predominantly short — hedging real physical exposure. "
                    "When commercials COVER shorts (reduce hedges), it signals they see value at current prices. "
                    "This is historically the most reliable bullish COT signal. "
                    "Swap dealer positioning reflects bank hedging demand — not directional.", C["amber"]), md=6),
            ]),
        ])

    # ── NEWS ──────────────────────────────────────────────────────────────────
    elif tab == "news":
        if not news:
            return html.Div("No news available — feeds may be temporarily unavailable.",
                            style={"color":C["muted"],"padding":"20px","fontSize":"12px"})
        cols = [[], [], []]
        for i, a in enumerate(news):
            cols[i % 3].append(news_card(a))
        return html.Div([
            sec("Market News", "Reuters, EIA, FT, Platts — refreshed hourly"),
            dbc.Row([dbc.Col(cols[0],md=4), dbc.Col(cols[1],md=4), dbc.Col(cols[2],md=4)]),
        ])

    return html.Div("Select a tab.", style={"color": C["muted"]})


# ── Run ───────────────────────────────────────────────────────────────────────
port = int(os.environ.get("PORT", 8050))
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=port)
