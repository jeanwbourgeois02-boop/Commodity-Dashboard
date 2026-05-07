"""
Commodity Intelligence Dashboard — Phase 1
Sources: OilPriceAPI (commodities), Twelve Data (equities/macro), EIA (inventories), CFTC (COT)
Run: python app.py → open http://localhost:8050
"""

import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import requests
import feedparser
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

C = {
    "bg":      "#0f1117",
    "surface": "#1a1d27",
    "card":    "#21253a",
    "border":  "#2e3352",
    "accent":  "#4f6ef7",
    "green":   "#26c281",
    "red":     "#e05252",
    "amber":   "#f0a500",
    "teal":    "#20c9b0",
    "purple":  "#9b59b6",
    "text":    "#e8eaf6",
    "muted":   "#7b82a8",
}

# ── API Keys ──────────────────────────────────────────────────────────────────
OIL_KEY  = "799133b15930b2ffdf9835f8e09c980b232eecab16be00f2956d91de1da5af98"
OIL_BASE = "https://api.oilpriceapi.com/v1"
OIL_HDR  = {"Authorization": f"Token {OIL_KEY}", "Content-Type": "application/json"}

TD_KEY   = "d01faaa78c0b467f93d8b35dc09ee7fc"
TD_BASE  = "https://api.twelvedata.com"

EIA_KEY  = "GJf5HWhOHneOmzBuq0pwz1xWbSLwdgy63McZGJqY"
EIA_BASE = "https://api.eia.gov/v2"

# ── OilPriceAPI commodity codes ───────────────────────────────────────────────
OIL_COMMODITIES = {
    # Crude
    "Brent Crude":       "BRENT_CRUDE_USD",
    "WTI Crude":         "WTI_USD",
    "Dubai Crude":       "DUBAI_CRUDE_USD",
    "Urals Crude":       "URALS_CRUDE_USD",
    "WTI Midland":       "WTI_MIDLAND_USD",
    "OPEC Basket":       "OPEC_BASKET_USD",
    # Products
    "Gasoline (RBOB)":   "GASOLINE_RBOB_USD",
    "ULSD Diesel":       "ULSD_DIESEL_USD",
    "Jet Fuel":          "JET_FUEL_USD",
    "Heating Oil":       "HEATING_OIL_USD",
    # Gas
    "Henry Hub Gas":     "NATURAL_GAS_USD",
    "Dutch TTF Gas":     "DUTCH_TTF_NATURAL_GAS_USD",
    "JKM LNG":           "JKM_LNG_USD",
    # Marine fuels
    "VLSFO":             "VLSFO_USD",
    "HSFO 380":          "HFO_380_USD",
    "MGO":               "MGO_05S_USD",
}

# ── Twelve Data symbols (equities, ETFs, indices, forex) ─────────────────────
TD_INSTRUMENTS = {
    "S&P 500":           "SPX",
    "XLE Energy ETF":    "XLE",
    "XOP Oil & Gas":     "XOP",
    "ExxonMobil":        "XOM",
    "Shell":             "SHEL",
    "BP":                "BP",
    "TotalEnergies":     "TTE",
    "Valero":            "VLO",
    "Marathon Pete":     "MPC",
    "Euronav (VLCC)":    "EURN",
    "DHT Holdings":      "DHT",
    "Frontline":         "FRO",
    "Flex LNG":          "FLNG",
    "Golar LNG":         "GLNG",
    "BDRY Dry Bulk":     "BDRY",
    "Gold":              "XAU/USD",
    "Copper":            "XCU/USD",
    "Silver":            "XAG/USD",
    "DXY":               "DXY",
    "US 10Y Yield":      "TNX",
    "VIX":               "VIX",
    "EUR/USD":           "EUR/USD",
    "USD/CNY":           "USD/CNY",
}

NEWS_FEEDS = [
    ("Reuters",  "https://feeds.reuters.com/reuters/businessNews"),
    ("EIA",      "https://www.eia.gov/rss/news.xml"),
    ("FT",       "https://www.ft.com/commodities?format=rss"),
    ("Platts",   "https://www.spglobal.com/commodityinsights/en/rss-feed/oil"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def oil_latest(code: str) -> dict | None:
    """Fetch latest price from OilPriceAPI."""
    try:
        r = requests.get(f"{OIL_BASE}/prices/latest",
                         params={"by_code": code}, headers=OIL_HDR, timeout=8)
        d = r.json()
        if d.get("status") != "success":
            return None
        price = float(d["data"]["price"])
        return {"price": price, "chg": 0, "pct": 0}
    except Exception:
        return None


def oil_past_week(code: str) -> list:
    """Fetch past week of prices from OilPriceAPI."""
    try:
        r = requests.get(f"{OIL_BASE}/prices/past_week",
                         params={"by_code": code}, headers=OIL_HDR, timeout=8)
        d = r.json()
        if d.get("status") != "success":
            return []
        return d.get("data", [])
    except Exception:
        return []


def oil_past_day(code: str) -> dict | None:
    """Get today + yesterday to calculate change."""
    pts = oil_past_week(code)
    if len(pts) < 2:
        p = oil_latest(code)
        return p
    try:
        latest = float(pts[0]["price"])
        prev   = float(pts[1]["price"])
        chg    = latest - prev
        pct    = (chg / prev * 100) if prev else 0
        return {"price": latest, "chg": chg, "pct": pct}
    except Exception:
        return None


def fetch_oil_history(code: str, days: int = 365) -> pd.DataFrame:
    """Fetch historical prices from OilPriceAPI."""
    try:
        end   = datetime.utcnow()
        start = end - timedelta(days=days)
        r = requests.get(f"{OIL_BASE}/prices",
                         params={
                             "by_code": code,
                             "by_period": "daily",
                             "start_at": start.strftime("%Y-%m-%dT00:00:00Z"),
                             "end_at":   end.strftime("%Y-%m-%dT23:59:59Z"),
                         },
                         headers=OIL_HDR, timeout=15)
        d = r.json()
        if d.get("status") != "success":
            return pd.DataFrame()
        pts = d.get("data", [])
        if not pts:
            return pd.DataFrame()
        df = pd.DataFrame(pts)
        df["date"]  = pd.to_datetime(df["created_at"]).dt.normalize()
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.groupby("date")["price"].last().reset_index()
        df = df.set_index("date").sort_index().dropna()
        return df
    except Exception:
        return pd.DataFrame()


def td_quote(sym: str) -> dict | None:
    """Fetch quote from Twelve Data."""
    try:
        r = requests.get(f"{TD_BASE}/quote",
                         params={"symbol": sym, "apikey": TD_KEY}, timeout=8)
        d = r.json()
        if "code" in d:
            return None
        price = float(d.get("close") or d.get("price") or 0)
        prev  = float(d.get("previous_close") or price)
        chg   = price - prev
        pct   = (chg / prev * 100) if prev else 0
        return {"price": price, "chg": chg, "pct": pct}
    except Exception:
        return None


def td_history(sym: str, days: int = 365) -> pd.DataFrame:
    """Fetch time series from Twelve Data."""
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
        }, timeout=15)
        d = r.json()
        vals = d.get("values", [])
        if not vals:
            return pd.DataFrame()
        df = pd.DataFrame(vals)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df["price"]    = pd.to_numeric(df["close"], errors="coerce")
        return df.set_index("datetime").sort_index()[["price"]].dropna()
    except Exception:
        return pd.DataFrame()


def fetch_all_prices() -> dict:
    """Fetch all prices — oil via OilPriceAPI, equities via Twelve Data."""
    result = {}

    # Commodity prices via OilPriceAPI
    for name, code in OIL_COMMODITIES.items():
        p = oil_past_day(code)
        if p:
            result[name] = {**p, "source": "oil"}

    # Equity/macro prices via Twelve Data
    for name, sym in TD_INSTRUMENTS.items():
        p = td_quote(sym)
        if p:
            result[name] = {**p, "source": "td", "sym": sym}

    return result


def fetch_history_for(name: str, days: int = 365) -> pd.DataFrame:
    """Fetch history for a named instrument."""
    if name in OIL_COMMODITIES:
        return fetch_oil_history(OIL_COMMODITIES[name], days)
    elif name in TD_INSTRUMENTS:
        return td_history(TD_INSTRUMENTS[name], days)
    return pd.DataFrame()


def fetch_eia(series_id: str, length: int = 104) -> pd.DataFrame:
    url = (f"{EIA_BASE}/petroleum/stoc/wstk/data/"
           f"?api_key={EIA_KEY}&frequency=weekly"
           f"&data[0]=value&facets[series][]={series_id}"
           f"&sort[0][column]=period&sort[0][direction]=desc&length={length}")
    try:
        r    = requests.get(url, timeout=10)
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


def fetch_cot() -> pd.DataFrame:
    url = ("https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
           "?commodity_name=CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE"
           "&$order=report_date_as_yyyy_mm_dd DESC&$limit=52")
    try:
        r    = requests.get(url, timeout=10)
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


def fetch_news() -> list:
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
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def sec_header(title: str, sub: str = "") -> html.Div:
    return html.Div([
        html.H5(title, style={"color": C["text"], "margin": "0 0 2px 0", "fontWeight": "600"}),
        html.Div(sub,  style={"color": C["muted"], "fontSize": "12px"}),
    ], style={"borderLeft": f"3px solid {C['accent']}", "paddingLeft": "10px",
              "marginBottom": "16px"})


def price_card(name: str, d: dict) -> dbc.Col:
    up  = d["pct"] >= 0
    col = C["green"] if up else C["red"]
    arr = "▲" if up else "▼"
    return dbc.Col(html.Div([
        html.Div(name, style={"fontSize": "11px", "color": C["muted"],
                               "marginBottom": "3px", "fontWeight": "500"}),
        html.Div(f"{d['price']:,.2f}",
                 style={"fontSize": "20px", "color": C["text"], "fontWeight": "600"}),
        html.Div(f"{arr} {abs(d['pct']):.2f}%  ({d['chg']:+.2f})",
                 style={"fontSize": "11px", "color": col, "marginTop": "2px"}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "8px", "padding": "12px 14px"}),
    xs=6, sm=4, md=3, lg=2, style={"marginBottom": "10px"})


def empty_card(name: str) -> dbc.Col:
    return dbc.Col(html.Div([
        html.Div(name, style={"fontSize": "11px", "color": C["muted"], "marginBottom": "3px"}),
        html.Div("—", style={"fontSize": "20px", "color": C["muted"]}),
        html.Div("loading...", style={"fontSize": "11px", "color": C["muted"]}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "8px", "padding": "12px 14px"}),
    xs=6, sm=4, md=3, lg=2, style={"marginBottom": "10px"})


def price_row(names: list, prices: dict) -> dbc.Row:
    return dbc.Row(
        [price_card(n, prices[n]) if n in prices else empty_card(n) for n in names],
        style={"marginBottom": "20px"}
    )


def make_line_chart(name: str, title: str, color: str = None,
                    days: int = 365, height: int = 200) -> go.Figure:
    color = color or C["accent"]
    df    = fetch_history_for(name, days)
    fig   = go.Figure()
    if not df.empty:
        vals = df["price"].values.flatten()
        fig.add_trace(go.Scatter(
            x=df.index, y=vals, mode="lines",
            line=dict(color=color, width=1.8),
            fill="tozeroy", fillcolor=color + "12",
            hovertemplate="%{y:.2f}<extra></extra>",
        ))
    else:
        fig.add_annotation(text="Loading...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"], size=11))
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=6, r=6, t=30, b=6),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=9)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=9)),
        height=height, showlegend=False,
    )
    return fig


def make_spread_chart(name_a: str, name_b: str, title: str,
                      mult_a: float = 1.0, mult_b: float = 1.0,
                      days: int = 365) -> go.Figure:
    fig = go.Figure()
    try:
        a = fetch_history_for(name_a, days)
        b = fetch_history_for(name_b, days)
        if a.empty or b.empty:
            raise ValueError()
        df = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
        df["spread"] = df["price_a"] * mult_a - df["price_b"] * mult_b
        vals = df["spread"].values.flatten()
        avg  = float(df["spread"].mean())
        col  = C["green"] if float(vals[-1]) > avg else C["red"]
        fig.add_trace(go.Scatter(x=df.index, y=vals, mode="lines",
            line=dict(color=col, width=1.8), fill="tozeroy",
            fillcolor=col + "12", hovertemplate="%{y:.2f}<extra></extra>"))
        fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"], opacity=0.5,
                      annotation_text=f"1yr avg: {avg:.2f}",
                      annotation_font_color=C["amber"], annotation_font_size=9)
        latest = float(vals[-1])
        vs = latest - avg
        fig.add_annotation(
            text=f"Now: {latest:.2f}  vs avg: {'+' if vs>=0 else ''}{vs:.2f}",
            x=0.98, y=0.92, xref="paper", yref="paper",
            showarrow=False, font=dict(color=C["green"] if vs >= 0 else C["red"], size=10))
    except Exception:
        fig.add_annotation(text="Loading...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"], size=11))
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=6, r=6, t=30, b=6),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=9)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=9)),
        height=200, showlegend=False,
    )
    return fig


def eia_chart(df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    if not df.empty:
        d52  = df.tail(52)
        avg  = float(df["value"].mean())
        col  = C["red"] if float(d52["value"].iloc[-1]) > avg else C["green"]
        fig.add_trace(go.Scatter(x=d52["period"],
            y=d52["value"].values.flatten(), mode="lines",
            line=dict(color=col, width=2),
            hovertemplate="%{x|%b %d}: %{y:,.0f}<extra></extra>"))
        fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"], opacity=0.6,
                      annotation_text="2yr avg", annotation_font_color=C["amber"])
        latest = float(d52["value"].iloc[-1])
        diff   = latest - avg
        fig.add_annotation(
            text=f"vs avg: {'+' if diff>=0 else ''}{diff:,.0f}k",
            x=0.98, y=0.95, xref="paper", yref="paper",
            showarrow=False, font=dict(color=col, size=10))
    else:
        fig.add_annotation(text="Fetching EIA data...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"], size=11))
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=6, r=6, t=30, b=6),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=9)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=9)),
        height=200,
    )
    return fig


def info_box(title: str, body: str, color: str = None) -> html.Div:
    color = color or C["accent"]
    return html.Div([
        html.Div(title, style={"fontSize": "12px", "fontWeight": "600",
                                "color": color, "marginBottom": "5px"}),
        html.Div(body,  style={"fontSize": "12px", "color": C["text"],
                                "lineHeight": "1.55"}),
    ], style={"background": C["card"], "border": f"1px solid {color}33",
              "borderLeft": f"3px solid {color}", "borderRadius": "6px",
              "padding": "10px 14px", "marginBottom": "8px"})


def news_card(a: dict) -> html.Div:
    return html.Div([
        html.Div(a["source"], style={"fontSize": "10px", "color": C["accent"],
                                      "fontWeight": "600", "marginBottom": "3px"}),
        html.A(a["title"], href=a["link"], target="_blank",
               style={"color": C["text"], "fontSize": "12px",
                      "textDecoration": "none", "display": "block", "lineHeight": "1.4"}),
        html.Div(a.get("time", ""), style={"fontSize": "10px",
                                            "color": C["muted"], "marginTop": "3px"}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "6px", "padding": "10px 12px", "marginBottom": "8px"})


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

TS = {"color": C["muted"], "backgroundColor": "transparent", "border": "none",
      "padding": "13px 16px", "fontSize": "13px", "fontWeight": "500"}
TS_SEL = {**TS, "color": C["accent"],
          "borderBottom": f"2px solid {C['accent']}", "fontWeight": "600"}

app.layout = html.Div(
    style={"background": C["bg"], "minHeight": "100vh",
           "fontFamily": "'Inter','Segoe UI',sans-serif"},
    children=[
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Span("◈ ", style={"color": C["accent"], "fontSize": "18px"}),
                    html.Span("COMMODITY INTELLIGENCE",
                              style={"color": C["text"], "fontSize": "15px",
                                     "fontWeight": "700", "letterSpacing": "2px"}),
                ], width="auto"),
                dbc.Col(html.Div(id="ts", style={"color": C["muted"], "fontSize": "11px",
                                                   "textAlign": "right", "paddingTop": "4px"})),
                dbc.Col(dbc.Button("↻ Refresh", id="refresh-btn", size="sm",
                                   style={"background": C["accent"]+"22",
                                          "border": f"1px solid {C['accent']}55",
                                          "color": C["accent"], "fontSize": "12px",
                                          "borderRadius": "6px"}),
                        width="auto"),
            ], align="center", style={"padding": "12px 0"}),
        ], style={"background": C["surface"], "borderBottom": f"1px solid {C['border']}",
                  "padding": "0 20px", "position": "sticky", "top": "0", "zIndex": "100"}),

        dcc.Tabs(id="tabs", value="crude",
                 style={"background": C["surface"],
                        "borderBottom": f"1px solid {C['border']}"},
                 children=[
            dcc.Tab(label="🛢  Crude Oil",     value="crude",    style=TS, selected_style=TS_SEL),
            dcc.Tab(label="⚗️  Products",       value="products", style=TS, selected_style=TS_SEL),
            dcc.Tab(label="🔥  Gas & LNG",      value="gas",      style=TS, selected_style=TS_SEL),
            dcc.Tab(label="🚢  Freight",         value="freight",  style=TS, selected_style=TS_SEL),
            dcc.Tab(label="📊  Macro & Metals",  value="macro",    style=TS, selected_style=TS_SEL),
            dcc.Tab(label="📋  Positioning",     value="position", style=TS, selected_style=TS_SEL),
            dcc.Tab(label="📰  News",            value="news",     style=TS, selected_style=TS_SEL),
        ]),

        html.Div(id="content", style={"padding": "20px 24px"}),
        dcc.Interval(id="interval", interval=300_000, n_intervals=0),
        dcc.Store(id="store"),
    ]
)

# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(
    Output("store", "data"),
    Output("ts", "children"),
    Input("interval", "n_intervals"),
    Input("refresh-btn", "n_clicks"),
)
def refresh(_, __):
    prices = fetch_all_prices()
    ts     = datetime.utcnow().strftime("Updated %H:%M UTC")
    return prices, ts


@app.callback(
    Output("content", "children"),
    Input("tabs",  "value"),
    Input("store", "data"),
)
def render(tab, prices):
    prices = prices or {}

    # ── CRUDE OIL ─────────────────────────────────────────────────────────────
    if tab == "crude":
        crude_names = ["Brent Crude", "WTI Crude", "Dubai Crude",
                       "Urals Crude", "WTI Midland", "OPEC Basket"]

        brent = prices.get("Brent Crude",  {}).get("price", 0)
        wti   = prices.get("WTI Crude",    {}).get("price", 0)
        dubai = prices.get("Dubai Crude",  {}).get("price", 0)
        urals = prices.get("Urals Crude",  {}).get("price", 0)

        spread_strip = dbc.Row([
            dbc.Col(html.Div([
                html.Div("Brent – WTI", style={"fontSize":"11px","color":C["muted"]}),
                html.Div(f"${brent-wti:.2f}/bbl" if brent and wti else "—",
                         style={"fontSize":"18px","fontWeight":"600",
                                "color":C["green"] if brent>wti else C["red"]}),
                html.Div("Atlantic arb / US export driver",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=3),
            dbc.Col(html.Div([
                html.Div("Brent – Dubai (EFS proxy)", style={"fontSize":"11px","color":C["muted"]}),
                html.Div(f"${brent-dubai:.2f}/bbl" if brent and dubai else "—",
                         style={"fontSize":"18px","fontWeight":"600",
                                "color":C["green"] if brent>dubai else C["red"]}),
                html.Div("Drives east/west crude routing",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=3),
            dbc.Col(html.Div([
                html.Div("Urals discount to Brent", style={"fontSize":"11px","color":C["muted"]}),
                html.Div(f"${urals-brent:.2f}/bbl" if brent and urals else "—",
                         style={"fontSize":"18px","fontWeight":"600","color":C["amber"]}),
                html.Div("Russian crude discount — sanctions signal",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=3),
            dbc.Col(html.Div([
                html.Div("OPEC+ spare capacity", style={"fontSize":"11px","color":C["muted"]}),
                html.Div("~3mb/d est.", style={"fontSize":"18px","fontWeight":"600","color":C["amber"]}),
                html.Div("Low spare = high geopolitical premium",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=3),
        ], style={"marginBottom":"20px"})

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=make_line_chart("Brent Crude","Brent Crude — 1yr",C["accent"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_line_chart("WTI Crude","WTI Crude — 1yr",C["teal"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_spread_chart("Brent Crude","WTI Crude","Brent – WTI Spread $/bbl"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_spread_chart("Brent Crude","Dubai Crude","Brent – Dubai Spread $/bbl"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"20px"})

        eia_crude = fetch_eia("WCRSTUS1", 104)
        eia_cush  = fetch_eia("WCSSTUS1", 104)
        inv_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=eia_chart(eia_crude,"US Crude Stocks (k bbls) — EIA weekly"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=eia_chart(eia_cush, "Cushing OK Stocks (k bbls) — WTI delivery"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("OPEC+ Supply",
                    "Voluntary cuts ~3.66mb/d above 2022 baseline. Watch monthly production vs quota — "
                    "Iraq, UAE, Kazakhstan historically over-produce. Any unwind of cuts is bearish. "
                    "Compliance data released ~2 weeks after month-end.", C["amber"]),
                info_box("US Shale",
                    "Production ~13.5mb/d. Responds to price with 3-6 month lag. Permian drives marginal growth. "
                    "Baker Hughes rig count (Fridays) = leading indicator for supply 6 months out.", C["teal"]),
                info_box("Russia Post-Sanctions",
                    "Most Urals going to India/China at discount to Brent. "
                    "Shadow fleet (~600 vessels) carries this flow. "
                    "Discount compression = less incentive for buyers.", C["purple"]),
            ], md=6),
            dbc.Col([
                info_box("China Demand",
                    "~16mb/d, world's largest crude importer. Key signals: customs data (monthly crude imports), "
                    "teapot refinery runs, SPR build/draw cycles. EV penetration ~35% new car sales.", C["green"]),
                info_box("How Dated Brent is Set",
                    "Physical price set in the Platts Price Window, 4:00-4:30pm London daily. "
                    "BFOET basket (Brent, Forties, Oseberg, Ekofisk, Troll). "
                    "Forties usually cheapest and price-setting.", C["accent"]),
                info_box("Geopolitical Premium",
                    "Strait of Hormuz: ~20% of global oil flows. "
                    "EIA April 2026: Brent forecast to peak ~$115/b on Hormuz closure risk, "
                    "with 7.5mb/d of Gulf production shut in.", C["red"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Crude Oil", "Brent, WTI, Dubai, Urals — live prices, spreads, inventories"),
            price_row(crude_names, prices),
            spread_strip,
            sec_header("Price History & Spreads",""),
            charts,
            sec_header("EIA Inventories","Wednesday release 10:30am ET — most market-moving weekly data in oil"),
            inv_row,
            sec_header("Fundamental Context",""),
            context,
        ])

    # ── PRODUCTS ──────────────────────────────────────────────────────────────
    elif tab == "products":
        prod_names = ["Gasoline (RBOB)", "ULSD Diesel", "Jet Fuel",
                      "Heating Oil", "VLSFO", "HSFO 380", "MGO"]

        eia_gas  = fetch_eia("WGTSTUS1", 104)
        eia_dist = fetch_eia("WDISTUS1", 104)
        eia_util = fetch_eia("WPULEUS3", 104)

        inv_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=eia_chart(eia_gas,  "US Gasoline Stocks (k bbls)"),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=eia_chart(eia_dist, "US Distillate Stocks (k bbls)"),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=eia_chart(eia_util, "US Refinery Utilisation (%)"),
                              config={"displayModeBar":False}), md=4),
        ], style={"marginBottom":"20px"})

        crack_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=make_spread_chart("Gasoline (RBOB)","Brent Crude",
                              "Gasoline Crack vs Brent $/gal"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_spread_chart("ULSD Diesel","Brent Crude",
                              "Diesel Crack vs Brent $/gal"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_spread_chart("Jet Fuel","Brent Crude",
                              "Jet Fuel Crack vs Brent $/gal"),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_spread_chart("ULSD Diesel","Gasoline (RBOB)",
                              "Diesel – Gasoline Spread"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"20px"})

        marine_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=make_line_chart("VLSFO","VLSFO (IMO 2020 bunker fuel)",C["teal"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("HSFO 380","HSFO 380 (high sulphur fuel oil)",C["red"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_spread_chart("VLSFO","HSFO 380","VLSFO–HSFO spread (Hi-5)"),
                              config={"displayModeBar":False}), md=4),
        ], style={"marginBottom":"20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("Crack Spreads",
                    "Crack spread = product price − crude. Measures refinery profitability. "
                    "High cracks → refiners run hard → more crude demand → bullish crude. "
                    "3-2-1 crack = (2×gasoline + 1×diesel − 3×crude) / 3.", C["accent"]),
                info_box("Gasoline Seasonality",
                    "US driving season Memorial Day → Labor Day (May–Sept). "
                    "Gasoline crack peaks spring/summer. RVP spec changes in summer tighten supply.", C["green"]),
            ], md=6),
            dbc.Col([
                info_box("Marine Fuels — IMO 2020",
                    "IMO 2020 capped sulphur in bunker fuel at 0.5% (from 3.5%). "
                    "Created VLSFO demand and Hi-5 spread (VLSFO vs HSFO). "
                    "Hi-5 spread is a key signal for refinery complexity margins.", C["amber"]),
                info_box("Jet Fuel Recovery",
                    "Jet fuel crack now strongest product margin globally as aviation recovers. "
                    "Watch IATA monthly passenger data — leading indicator for jet demand. "
                    "Asia-Pacific recovery the key swing factor.", C["teal"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Refined Products & Marine Fuels",
                       "Gasoline, diesel, jet, heating oil, VLSFO, HSFO — crack spreads and inventory"),
            price_row(prod_names, prices),
            sec_header("EIA Product Inventories & Refinery Runs",""),
            inv_row,
            sec_header("Crack Spreads — 1yr",""),
            crack_row,
            sec_header("Marine Fuels & Hi-5 Spread",""),
            marine_row,
            sec_header("Context",""),
            context,
        ])

    # ── GAS & LNG ─────────────────────────────────────────────────────────────
    elif tab == "gas":
        gas_names = ["Henry Hub Gas", "Dutch TTF Gas", "JKM LNG",
                     "Flex LNG", "Golar LNG"]

        henry = prices.get("Henry Hub Gas", {}).get("price", 0)
        ttf   = prices.get("Dutch TTF Gas", {}).get("price", 0)
        jkm   = prices.get("JKM LNG",       {}).get("price", 0)

        spread_strip = dbc.Row([
            dbc.Col(html.Div([
                html.Div("Henry Hub ($/MMBtu)", style={"fontSize":"11px","color":C["muted"]}),
                html.Div(f"${henry:.2f}" if henry else "—",
                         style={"fontSize":"18px","fontWeight":"600","color":C["teal"]}),
                html.Div("US benchmark — export LNG base cost",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=4),
            dbc.Col(html.Div([
                html.Div("Dutch TTF ($/MMBtu equiv)", style={"fontSize":"11px","color":C["muted"]}),
                html.Div(f"${ttf:.2f}" if ttf else "—",
                         style={"fontSize":"18px","fontWeight":"600","color":C["accent"]}),
                html.Div("European gas benchmark",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=4),
            dbc.Col(html.Div([
                html.Div("JKM LNG ($/MMBtu)", style={"fontSize":"11px","color":C["muted"]}),
                html.Div(f"${jkm:.2f}" if jkm else "—",
                         style={"fontSize":"18px","fontWeight":"600","color":C["purple"]}),
                html.Div("Asian LNG spot — routing signal",
                         style={"fontSize":"10px","color":C["muted"]}),
            ], style={"background":C["card"],"borderRadius":"8px",
                      "padding":"10px 14px","border":f"1px solid {C['border']}"}), md=4),
        ], style={"marginBottom":"20px"})

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=make_line_chart("Henry Hub Gas","Henry Hub — 1yr",C["teal"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_line_chart("Dutch TTF Gas","Dutch TTF Gas — 1yr",C["accent"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_line_chart("JKM LNG","JKM LNG — 1yr",C["purple"]),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_spread_chart("Dutch TTF Gas","Henry Hub Gas",
                              "TTF – Henry Hub Spread (European vs US gas)"),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("The LNG Routing Decision",
                    "US LNG goes east if JKM > Henry Hub + $3 liquefaction + freight (~$1-2). "
                    "Goes to Europe if TTF > JKM + freight. This spread drives real-time routing decisions "
                    "by Vitol, Shell, TotalEnergies on every cargo.", C["teal"]),
                info_box("European Gas Storage",
                    "GIE AGSI data — % full vs seasonal norms. EU winter target ~90% full. "
                    "Summer injection season April–October. Storage deficit = TTF bullish. "
                    "Russia pipeline gas now minimal — Europe structurally dependent on LNG.", C["amber"]),
            ], md=6),
            dbc.Col([
                info_box("JKM Volatility",
                    "Asian LNG spot is the most volatile benchmark. Cold snap in NE Asia "
                    "spikes JKM $3-5 in days — diverts Atlantic cargoes eastward immediately. "
                    "Japan/Korea nuclear outages also drive demand spikes.", C["purple"]),
                info_box("US LNG Export Capacity",
                    "US now world's largest LNG exporter (~14 bcf/d). "
                    "Sabine Pass, Freeport, Corpus Christi, Cameron are key terminals. "
                    "Any outage (like Freeport 2022) removes supply and spikes TTF.", C["green"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Natural Gas & LNG", "Henry Hub, TTF, JKM — the three global gas benchmarks"),
            price_row(gas_names, prices),
            spread_strip,
            sec_header("Price History",""),
            charts,
            sec_header("Fundamental Context",""),
            context,
        ])

    # ── FREIGHT ───────────────────────────────────────────────────────────────
    elif tab == "freight":
        freight_names = ["Euronav (VLCC)","DHT Holdings","Frontline",
                         "Flex LNG","Golar LNG","BDRY Dry Bulk"]

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=make_line_chart("Euronav (VLCC)","Euronav — VLCC proxy",C["accent"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("Frontline","Frontline — tanker proxy",C["teal"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("BDRY Dry Bulk","BDRY — Baltic Dry ETF",C["amber"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("Flex LNG","Flex LNG — LNG shipping",C["purple"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("DHT Holdings","DHT Holdings — VLCC",C["green"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("Golar LNG","Golar LNG",C["muted"]),
                              config={"displayModeBar":False}), md=4),
        ], style={"marginBottom":"20px"})

        routes = [
            ("TD3C — VLCC (ME Gulf → China)", C["accent"],
             "Benchmark VLCC route, 2mb cargo. Rates driven by OPEC+ export volumes and Chinese crude demand. "
             "High Worldscale = tight tonnage = bullish crude demand. Euronav, DHT, Frontline are proxies."),
            ("TD20 — Suezmax (W.Africa → Europe)", C["teal"],
             "Key for Nigerian/Angolan crude into European refineries. "
             "Rates rise when Atlantic basin crude flows strongly westward."),
            ("LNG Shipping", C["purple"],
             "Spot day rates range $40-180k/day. Spike in winter on NE Asia demand. "
             "Low in summer shoulder. Flex LNG and Golar LNG are listed proxies."),
            ("Baltic Dry Index", C["amber"],
             "Dry bulk: iron ore, coal, grain. Capesize (iron ore/coal), Panamax (grain/coal). "
             "Rising BDI = rising Chinese steel production = industrial demand signal."),
            ("TC2 — MR Tanker (ARA → USAC)", C["green"],
             "Clean products tanker route. Tight TC2 = strong transatlantic gasoline arb. "
             "Watches Colonial Pipeline and ARA product stock levels."),
            ("Shadow Fleet", C["red"],
             "~600-700 vessels carrying Russian/Iranian/Venezuelan crude. Absorbs global tanker capacity. "
             "When shadow fleet utilisation rises, mainstream freight tightens. Track via Kpler AIS."),
        ]

        return html.Div([
            sec_header("Freight & Shipping","Tanker rates, dry bulk, LNG shipping — listed equity proxies"),
            price_row(freight_names, prices),
            sec_header("Shipping Equity Proxies — 1yr",""),
            charts,
            sec_header("Key Routes & Signals",""),
            dbc.Row([dbc.Col(info_box(t, b, c), md=6) for t, c, b in routes]),
        ])

    # ── MACRO & METALS ────────────────────────────────────────────────────────
    elif tab == "macro":
        macro_names = ["S&P 500","XLE Energy ETF","XOP Oil & Gas",
                       "ExxonMobil","Valero","Gold","Copper",
                       "DXY","US 10Y Yield","VIX","EUR/USD","USD/CNY"]

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=make_line_chart("DXY","DXY USD Index — 1yr",C["amber"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("Gold","Gold — 1yr",C["amber"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("Copper","Copper — 1yr",C["teal"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("US 10Y Yield","US 10Y Yield — 1yr",C["red"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("VIX","VIX — 1yr",C["purple"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_line_chart("XLE Energy ETF","XLE Energy ETF — 1yr",C["green"]),
                              config={"displayModeBar":False}), md=4),
            dbc.Col(dcc.Graph(figure=make_spread_chart("Copper","Gold","Copper/Gold Ratio (×100)",mult_a=100.0),
                              config={"displayModeBar":False}), md=6),
            dbc.Col(dcc.Graph(figure=make_line_chart("XOP Oil & Gas","XOP Oil & Gas ETF — 1yr",C["accent"]),
                              config={"displayModeBar":False}), md=6),
        ], style={"marginBottom":"20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("DXY & Commodities",
                    "Commodities priced in USD — strong dollar = higher cost for EM importers = demand destruction. "
                    "DXY and Brent have strong negative correlation. "
                    "Watch real yields (TIPS) — negative real yields are very bullish for commodities.", C["amber"]),
                info_box("Copper as Global Barometer",
                    "Copper demand dominated by China (~55% of global consumption). "
                    "Rising copper = China industrial activity picking up = bullish for oil demand. "
                    "Copper-gold ratio rising = risk-on/growth. China credit impulse leads copper by 6-9 months.", C["teal"]),
            ], md=6),
            dbc.Col([
                info_box("Energy Equities vs Crude",
                    "XLE/XOP vs crude divergence is a useful signal. "
                    "Equities leading crude higher = market believes crude will rise (forward-looking). "
                    "Equities lagging crude = equity market sceptical. "
                    "HY energy credit spreads give the market's implied floor oil price.", C["green"]),
                info_box("VIX & Risk-Off",
                    "High VIX = risk-off = institutional deleveraging = all assets sold together. "
                    "In risk-off, commodities and equities correlate to 1. "
                    "After VIX spike and reversion, commodity vol often stays elevated — "
                    "creates opportunity to buy cheap back-month options.", C["purple"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Macro & Metals","DXY, yields, VIX, copper, gold, energy equities"),
            price_row(macro_names, prices),
            sec_header("Charts — 1yr",""),
            charts,
            sec_header("Inter-Market Signals",""),
            context,
        ])

    # ── POSITIONING ───────────────────────────────────────────────────────────
    elif tab == "position":
        cot_df    = fetch_cot()
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
            fig_net.add_hrect(y0=net_max*0.85, y1=net_max, fillcolor=C["red"], opacity=0.07,
                annotation_text="Crowded long", annotation_font_color=C["red"], annotation_font_size=10)
            fig_net.add_hrect(y0=net_min, y1=net_min*0.85, fillcolor=C["green"], opacity=0.07,
                annotation_text="Crowded short", annotation_font_color=C["green"], annotation_font_size=10)

            fig_gross.add_trace(go.Scatter(x=dates, y=longs.values.flatten(),
                mode="lines", name="Longs", line=dict(color=C["green"], width=1.8)))
            fig_gross.add_trace(go.Scatter(x=dates, y=shorts.values.flatten(),
                mode="lines", name="Shorts", line=dict(color=C["red"], width=1.8)))

            signal_col = C["red"] if net_pct > 75 else C["green"] if net_pct < 25 else C["amber"]
            signal_txt = ("⚠ Crowded long — reversal risk high"  if net_pct > 75 else
                          "⚠ Crowded short — squeeze risk high"   if net_pct < 25 else
                          "✓ Positioning neutral — no crowding signal")

        for fig, title in [
            (fig_net,   "WTI Crude — Managed Money Net Position (contracts)"),
            (fig_gross, "WTI Crude — Gross Longs vs Shorts"),
        ]:
            fig.update_layout(
                title=dict(text=title, font=dict(size=12, color=C["text"]), x=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=6, r=6, t=32, b=6),
                xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=9)),
                yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                           tickfont=dict(size=9)),
                legend=dict(font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
                height=260,
            )

        signal_card = html.Div([
            html.Div(signal_txt, style={"fontSize":"15px","fontWeight":"700","color":signal_col}),
            html.Div(f"Net: {latest_net:+,} contracts  |  {net_pct}th percentile vs 1yr range",
                     style={"fontSize":"12px","color":C["muted"],"marginTop":"5px"}),
        ], style={"background":C["card"],"border":f"1px solid {signal_col}44",
                  "borderLeft":f"3px solid {signal_col}","borderRadius":"8px",
                  "padding":"14px 18px","marginBottom":"18px"})

        return html.Div([
            sec_header("Positioning & COT","CFTC Commitment of Traders — managed money in WTI crude"),
            signal_card,
            dbc.Row([
                dbc.Col(dcc.Graph(figure=fig_net,   config={"displayModeBar":False}), md=6),
                dbc.Col(dcc.Graph(figure=fig_gross, config={"displayModeBar":False}), md=6),
            ], style={"marginBottom":"20px"}),
            dbc.Row([
                dbc.Col(info_box("How to Use the COT Report",
                    "CFTC Commitment of Traders released every Friday. "
                    "Shows managed money (hedge funds/CTAs) net positioning. "
                    "Extreme net long = crowded = reversal risk on any negative catalyst. "
                    "Use as a crowding indicator, not a standalone entry signal.", C["accent"]), md=6),
                dbc.Col(info_box("Commercials vs Specs",
                    "Commercials (producers, refiners) are predominantly short — hedging production. "
                    "If commercials are COVERING shorts, they see value at current prices. "
                    "This is the most bullish COT signal.", C["amber"]), md=6),
            ]),
        ])

    # ── NEWS ──────────────────────────────────────────────────────────────────
    elif tab == "news":
        articles = fetch_news()
        if not articles:
            return html.Div("No news available — check network.",
                            style={"color":C["muted"],"padding":"20px"})
        cols = [[], [], []]
        for i, a in enumerate(articles):
            cols[i % 3].append(news_card(a))
        return html.Div([
            sec_header("Market News","Live feeds — Reuters, EIA, FT, Platts"),
            dbc.Row([dbc.Col(cols[0],md=4), dbc.Col(cols[1],md=4), dbc.Col(cols[2],md=4)]),
        ])

    return html.Div("Select a tab.", style={"color": C["muted"]})


# ── Run ───────────────────────────────────────────────────────────────────────
port = int(os.environ.get("PORT", 8050))
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=port)
