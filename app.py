"""
Commodity Intelligence Dashboard — Phase 1
Organised by market vertical: Crude Oil, Products, Gas/LNG, Freight, Metals/Macro, News
Run: python app.py → open http://localhost:8050
"""

import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import yfinance as yf
import pandas as pd
import requests
import feedparser
from datetime import datetime
import os

# ── App ───────────────────────────────────────────────────────────────────────
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

EIA_API_KEY = "GJf5HWhOHneOmzBuq0pwz1xWbSLwdgy63McZGJqY"
EIA_BASE    = "https://api.eia.gov/v2"

# ═══════════════════════════════════════════════════════════════════════════════
# TICKER MAPS — by vertical
# ═══════════════════════════════════════════════════════════════════════════════

CRUDE_TICKERS = {
    "Brent Crude":     "BZ=F",
    "WTI Crude":       "CL=F",
    "Gasoline (RBOB)": "RB=F",   # used in products too
    "Heating Oil":     "HO=F",   # used in products too
    "Natural Gas":     "NG=F",
}

PRODUCTS_TICKERS = {
    "Gasoline (RBOB)": "RB=F",
    "Heating Oil/Diesel": "HO=F",
    "Brent Crude":     "BZ=F",
    "WTI Crude":       "CL=F",
}

GAS_TICKERS = {
    "Henry Hub (NG)":  "NG=F",
    "Flex LNG":        "FLNG",
    "Golar LNG":       "GLNG",
}

FREIGHT_TICKERS = {
    "Euronav (VLCC)":  "EURN",
    "DHT Holdings":    "DHT",
    "Frontline":       "FRO",
    "Flex LNG":        "FLNG",
    "Golar LNG":       "GLNG",
    "BDRY (Dry Bulk)": "BDRY",
    "Global Ship ETF": "BOAT",
}

MACRO_TICKERS = {
    "S&P 500":          "^GSPC",
    "Energy ETF (XLE)": "XLE",
    "Oil & Gas (XOP)":  "XOP",
    "ExxonMobil":       "XOM",
    "Shell":            "SHEL",
    "BP":               "BP",
    "TotalEnergies":    "TTE",
    "Valero":           "VLO",
    "Marathon":         "MPC",
    "Gold":             "GC=F",
    "Copper":           "HG=F",
    "DXY":              "DX-Y.NYB",
    "US 10Y Yield":     "^TNX",
    "VIX":              "^VIX",
    "EUR/USD":          "EURUSD=X",
    "USD/CNY":          "USDCNY=X",
}

NEWS_FEEDS = [
    ("Reuters",   "https://feeds.reuters.com/reuters/businessNews"),
    ("EIA",       "https://www.eia.gov/rss/news.xml"),
    ("FT",        "https://www.ft.com/commodities?format=rss"),
    ("Platts",    "https://www.spglobal.com/commodityinsights/en/rss-feed/oil"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_prices(tickers: dict) -> dict:
    """Returns {name: {price, chg, pct}} dict."""
    symbols = list(tickers.values())
    result  = {}
    try:
        data = yf.download(symbols, period="2d", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True)
        for name, sym in tickers.items():
            try:
                close = data[sym]["Close"].dropna() if len(symbols) > 1 else data["Close"].dropna()
                if len(close) < 1:
                    continue
                price = float(close.iloc[-1])
                prev  = float(close.iloc[-2]) if len(close) >= 2 else price
                chg   = price - prev
                pct   = (chg / prev * 100) if prev else 0
                result[name] = {"price": price, "chg": chg, "pct": pct, "sym": sym}
            except Exception:
                continue
    except Exception:
        pass
    return result


def fetch_history(sym: str, period: str = "1y") -> pd.DataFrame:
    try:
        df = yf.download(sym, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        return df[["Close"]].dropna().rename(columns={"Close": "price"})
    except Exception:
        return pd.DataFrame()


def fetch_eia(series_id: str, length: int = 104) -> pd.DataFrame:
    url = (f"{EIA_BASE}/petroleum/stoc/wstk/data/"
           f"?api_key={EIA_API_KEY}&frequency=weekly"
           f"&data[0]=value&facets[series][]={series_id}"
           f"&sort[0][column]=period&sort[0][direction]=desc&length={length}")
    try:
        r  = requests.get(url, timeout=10)
        d  = r.json()
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
                    "time":   e.get("published", ""),
                })
        except Exception:
            pass
    return articles[:24]


# ═══════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS
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
        html.Div(f"{d['price']:,.2f}", style={"fontSize": "20px",
                                               "color": C["text"], "fontWeight": "600"}),
        html.Div(f"{arr} {abs(d['pct']):.2f}%  ({d['chg']:+.2f})",
                 style={"fontSize": "11px", "color": col, "marginTop": "2px"}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "8px", "padding": "12px 14px"}),
    xs=6, sm=4, md=3, lg=2, style={"marginBottom": "10px"})


def line_chart(sym: str, title: str, color: str = None, period: str = "1y",
               height: int = 200) -> go.Figure:
    color = color or C["accent"]
    df    = fetch_history(sym, period)
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
                           showarrow=False, font=dict(color=C["muted"]))
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


def spread_chart(sym_a: str, sym_b: str, title: str, multiplier_a: float = 1.0,
                 multiplier_b: float = 1.0, period: str = "1y") -> go.Figure:
    fig = go.Figure()
    try:
        a = fetch_history(sym_a, period)
        b = fetch_history(sym_b, period)
        if a.empty or b.empty:
            raise ValueError("no data")
        df = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
        df["spread"] = (df["price_a"] * multiplier_a) - (df["price_b"] * multiplier_b)
        vals = df["spread"].values.flatten()
        avg  = float(df["spread"].mean())
        col  = C["green"] if float(vals[-1]) > avg else C["red"]
        fig.add_trace(go.Scatter(
            x=df.index, y=vals, mode="lines",
            line=dict(color=col, width=1.8),
            fill="tozeroy", fillcolor=col + "12",
            hovertemplate="%{y:.2f}<extra></extra>",
        ))
        fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"],
                      opacity=0.5, annotation_text=f"1yr avg: {avg:.2f}",
                      annotation_font_color=C["amber"], annotation_font_size=9)
        latest = float(vals[-1])
        vs = latest - avg
        sign = "+" if vs >= 0 else ""
        acol = C["green"] if vs >= 0 else C["red"]
        fig.add_annotation(text=f"Now: {latest:.2f}  vs avg: {sign}{vs:.2f}",
                           x=0.98, y=0.92, xref="paper", yref="paper",
                           showarrow=False, font=dict(color=acol, size=10))
    except Exception:
        fig.add_annotation(text="Loading...", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"]))
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


def info_box(title: str, body: str, color: str = None) -> html.Div:
    color = color or C["accent"]
    return html.Div([
        html.Div(title, style={"fontSize": "12px", "fontWeight": "600",
                                "color": color, "marginBottom": "5px"}),
        html.Div(body,  style={"fontSize": "12px", "color": C["text"],
                                "lineHeight": "1.5"}),
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
        html.Div(a.get("time", "")[:25], style={"fontSize": "10px",
                                                  "color": C["muted"], "marginTop": "3px"}),
    ], style={"background": C["card"], "border": f"1px solid {C['border']}",
              "borderRadius": "6px", "padding": "10px 12px", "marginBottom": "8px"})


# ═══════════════════════════════════════════════════════════════════════════════
# TAB STYLES
# ═══════════════════════════════════════════════════════════════════════════════

TS = {"color": C["muted"], "backgroundColor": "transparent", "border": "none",
      "padding": "13px 16px", "fontSize": "13px", "fontWeight": "500"}
TS_SEL = {**TS, "color": C["accent"], "borderBottom": f"2px solid {C['accent']}",
          "fontWeight": "600"}

# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

app.layout = html.Div(
    style={"background": C["bg"], "minHeight": "100vh",
           "fontFamily": "'Inter','Segoe UI',sans-serif"},
    children=[
        # Header
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

        # Main tabs
        dcc.Tabs(id="tabs", value="crude",
                 style={"background": C["surface"],
                        "borderBottom": f"1px solid {C['border']}"},
                 children=[
            dcc.Tab(label="🛢  Crude Oil",      value="crude",    style=TS, selected_style=TS_SEL),
            dcc.Tab(label="⚗️  Products",        value="products", style=TS, selected_style=TS_SEL),
            dcc.Tab(label="🔥  Gas & LNG",       value="gas",      style=TS, selected_style=TS_SEL),
            dcc.Tab(label="🚢  Freight",          value="freight",  style=TS, selected_style=TS_SEL),
            dcc.Tab(label="📊  Macro & Metals",   value="macro",    style=TS, selected_style=TS_SEL),
            dcc.Tab(label="📋  Positioning",      value="position", style=TS, selected_style=TS_SEL),
            dcc.Tab(label="📰  News",             value="news",     style=TS, selected_style=TS_SEL),
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
    all_tickers = {**CRUDE_TICKERS, **FREIGHT_TICKERS, **MACRO_TICKERS, **GAS_TICKERS}
    prices = fetch_prices(all_tickers)
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
        crude_names = ["Brent Crude", "WTI Crude"]
        price_cards = dbc.Row(
            [price_card(n, prices[n]) for n in crude_names if n in prices],
            style={"marginBottom": "20px"}
        )

        # Spread summary strip
        brent = prices.get("Brent Crude", {}).get("price", 0)
        wti   = prices.get("WTI Crude",   {}).get("price", 0)
        spreads_strip = dbc.Row([
            dbc.Col(html.Div([
                html.Div("Brent – WTI", style={"fontSize": "11px", "color": C["muted"]}),
                html.Div(f"${brent - wti:.2f}/bbl",
                         style={"fontSize": "16px", "fontWeight": "600",
                                "color": C["green"] if brent > wti else C["red"]}),
                html.Div("Atlantic arb / export driver", style={"fontSize": "10px", "color": C["muted"]}),
            ], style={"background": C["card"], "borderRadius": "8px", "padding": "10px 14px",
                      "border": f"1px solid {C['border']}"}), md=3),
            dbc.Col(html.Div([
                html.Div("Brent M1–M2 (time spread)", style={"fontSize": "11px", "color": C["muted"]}),
                html.Div("Live via ICE", style={"fontSize": "13px", "color": C["muted"]}),
                html.Div("Backwardation = physical tightness", style={"fontSize": "10px", "color": C["muted"]}),
            ], style={"background": C["card"], "borderRadius": "8px", "padding": "10px 14px",
                      "border": f"1px solid {C['border']}"}), md=3),
            dbc.Col(html.Div([
                html.Div("Brent – Dubai EFS", style={"fontSize": "11px", "color": C["muted"]}),
                html.Div("Drives E/W routing", style={"fontSize": "13px", "color": C["muted"]}),
                html.Div("High EFS → more Atlantic crude to Asia", style={"fontSize": "10px", "color": C["muted"]}),
            ], style={"background": C["card"], "borderRadius": "8px", "padding": "10px 14px",
                      "border": f"1px solid {C['border']}"}), md=3),
            dbc.Col(html.Div([
                html.Div("OPEC+ spare capacity signal", style={"fontSize": "11px", "color": C["muted"]}),
                html.Div("~3mb/d est. spare", style={"fontSize": "13px", "color": C["amber"]}),
                html.Div("Lower spare = higher geopolitical premium", style={"fontSize": "10px", "color": C["muted"]}),
            ], style={"background": C["card"], "borderRadius": "8px", "padding": "10px 14px",
                      "border": f"1px solid {C['border']}"}), md=3),
        ], style={"marginBottom": "20px"})

        # Charts
        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=line_chart("BZ=F", "Brent Crude — 1yr", C["accent"]),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=line_chart("CL=F", "WTI Crude — 1yr", C["teal"]),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=spread_chart("BZ=F", "CL=F", "Brent – WTI Spread $/bbl"),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(
                figure=line_chart("BZ=F", "Brent — 5yr view", C["purple"], period="5y", height=200),
                config={"displayModeBar": False}), md=6),
        ], style={"marginBottom": "20px"})

        # EIA inventories
        eia_crude = fetch_eia("WCRSTUS1", 104)
        eia_cush  = fetch_eia("WCSSTUS1", 104)

        def eia_fig(df, title):
            fig = go.Figure()
            if not df.empty:
                d52 = df.tail(52)
                avg = float(df["value"].mean())
                col = C["red"] if float(d52["value"].iloc[-1]) > avg else C["green"]
                fig.add_trace(go.Scatter(
                    x=d52["period"], y=d52["value"].values.flatten(),
                    mode="lines", line=dict(color=col, width=2),
                    hovertemplate="%{x|%b %d}: %{y:,.0f}k bbls<extra></extra>",
                ))
                fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"],
                              opacity=0.6, annotation_text="2yr avg",
                              annotation_font_color=C["amber"])
                latest = float(d52["value"].iloc[-1])
                diff   = latest - avg
                sign   = "+" if diff >= 0 else ""
                fig.add_annotation(
                    text=f"vs avg: {sign}{diff:,.0f}k bbls",
                    x=0.98, y=0.95, xref="paper", yref="paper",
                    showarrow=False, font=dict(color=col, size=10),
                )
            else:
                fig.add_annotation(text="Fetching EIA data...", x=0.5, y=0.5,
                                   showarrow=False, font=dict(color=C["muted"]))
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

        inv_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=eia_fig(eia_crude, "US Crude Stocks (k bbls) — EIA weekly"),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=eia_fig(eia_cush,  "Cushing OK Stocks (k bbls) — WTI delivery point"),
                              config={"displayModeBar": False}), md=6),
        ], style={"marginBottom": "20px"})

        # Fundamentals context
        context = dbc.Row([
            dbc.Col([
                info_box("OPEC+ Supply", "Current voluntary cuts ~3.66mb/d above 2022 baseline. "
                         "Watch monthly production vs quota — Iraq, UAE, Kazakhstan historically over-produce. "
                         "Any unwind of cuts is bearish. Compliance data released ~2 weeks after month-end.", C["amber"]),
                info_box("US Shale", "Production ~13.5mb/d. Responds to price with 3-6 month lag. "
                         "Permian drives marginal growth. Baker Hughes rig count released every Friday — "
                         "leading indicator for supply 6 months out.", C["teal"]),
                info_box("Russia (Post-Sanctions)", "Official production ~9.2mb/d. "
                         "Most Urals now going to India and China at $10-15 discount to Brent. "
                         "Shadow fleet (~600 vessels) tracks these flows. "
                         "Discount compression = less incentive for buyers = bearish for Urals.", C["purple"]),
            ], md=6),
            dbc.Col([
                info_box("China Demand", "~16mb/d, world's largest crude importer. "
                         "Key signals: customs data (crude imports monthly), teapot refinery runs, "
                         "SPR build/draw cycles. EV penetration now ~35% of new car sales — "
                         "structural headwind for gasoline demand.", C["green"]),
                info_box("Dated Brent — How Price is Set", "Physical price set in the Platts Price Window "
                         "4:00-4:30pm London daily. BFOET basket (Brent, Forties, Oseberg, Ekofisk, Troll). "
                         "Forties usually cheapest and price-setting. "
                         "Physical tightness here drives the paper market.", C["accent"]),
                info_box("Geopolitical Premium", "Strait of Hormuz: 20% of global oil. "
                         "Current EIA forecast: Brent peaking ~$115/b in Q2 2026 on Hormuz closure risk. "
                         "Options skew (upside calls vs puts) is the market-implied risk premium.", C["red"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Crude Oil", "Brent, WTI, spreads, inventories, fundamentals"),
            price_cards,
            spreads_strip,
            sec_header("Price History & Spreads", ""),
            charts,
            sec_header("EIA Inventories", "Weekly US crude stocks — Wednesday release, 10:30am ET"),
            inv_row,
            sec_header("Fundamental Context", "Supply, demand, and market mechanics"),
            context,
        ])

    # ── PRODUCTS ──────────────────────────────────────────────────────────────
    elif tab == "products":
        prod_names = ["Gasoline (RBOB)", "Heating Oil/Diesel"]
        price_cards = dbc.Row(
            [price_card(n, prices[n]) for n in prod_names if n in prices],
            style={"marginBottom": "20px"}
        )

        # EIA product inventories
        eia_gas  = fetch_eia("WGTSTUS1", 104)
        eia_dist = fetch_eia("WDISTUS1", 104)
        eia_util = fetch_eia("WPULEUS3", 104)

        def prod_eia_fig(df, title, unit="k bbls"):
            fig = go.Figure()
            if not df.empty:
                d52 = df.tail(52)
                avg = float(df["value"].mean())
                col = C["red"] if float(d52["value"].iloc[-1]) > avg else C["green"]
                fig.add_trace(go.Scatter(
                    x=d52["period"], y=d52["value"].values.flatten(),
                    mode="lines", line=dict(color=col, width=2),
                    hovertemplate=f"%{{x|%b %d}}: %{{y:,.0f}} {unit}<extra></extra>",
                ))
                fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"],
                              opacity=0.6, annotation_text=f"2yr avg",
                              annotation_font_color=C["amber"])
            else:
                fig.add_annotation(text="Fetching EIA data...", x=0.5, y=0.5,
                                   showarrow=False, font=dict(color=C["muted"]))
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

        inv_row = dbc.Row([
            dbc.Col(dcc.Graph(figure=prod_eia_fig(eia_gas,  "US Gasoline Stocks (k bbls)"),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=prod_eia_fig(eia_dist, "US Distillate Stocks (k bbls)"),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=prod_eia_fig(eia_util, "US Refinery Utilisation (%)", unit="%"),
                              config={"displayModeBar": False}), md=4),
        ], style={"marginBottom": "20px"})

        crack_row = dbc.Row([
            dbc.Col(dcc.Graph(
                figure=spread_chart("RB=F", "CL=F", "Gasoline Crack vs WTI $/bbl",
                                    multiplier_a=42.0),
                config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(
                figure=spread_chart("HO=F", "CL=F", "Diesel/Heat Crack vs WTI $/bbl",
                                    multiplier_a=42.0),
                config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(
                figure=spread_chart("RB=F", "BZ=F", "Gasoline Crack vs Brent $/bbl",
                                    multiplier_a=42.0),
                config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(
                figure=spread_chart("HO=F", "BZ=F", "Diesel Crack vs Brent $/bbl",
                                    multiplier_a=42.0),
                config={"displayModeBar": False}), md=6),
        ], style={"marginBottom": "20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("How Crack Spreads Work",
                         "Crack spread = product price − crude price. Measures refinery profitability. "
                         "High cracks → refiners run hard → more crude demand → bullish crude. "
                         "3-2-1 crack = (2×gasoline + 1×diesel − 3×crude) / 3.", C["accent"]),
                info_box("Gasoline Seasonality",
                         "US driving season Memorial Day → Labor Day (May-Sept). "
                         "Gasoline crack peaks spring/summer. RVP spec changes in summer "
                         "require different blending — tightens supply. Watch Colonial Pipeline rates.", C["green"]),
            ], md=6),
            dbc.Col([
                info_box("Diesel / Distillate",
                         "Diesel is the industrial fuel — strongest demand signal for global growth. "
                         "Heating oil peaks Q4/Q1. Jet fuel crack now strongest product margin globally "
                         "as aviation recovers. IMO 2020 tightened VLSFO/LSFO specs.", C["amber"]),
                info_box("Refinery Utilisation",
                         "US refinery utilisation above 90% = running near capacity. "
                         "Seasonal maintenance (typically March-April and Sept-Oct) drops runs, "
                         "tightening product supply and widening cracks temporarily.", C["teal"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Refined Products", "Gasoline, diesel, jet — crack spreads and inventories"),
            price_cards,
            sec_header("EIA Product Inventories & Refinery Runs", ""),
            inv_row,
            sec_header("Crack Spreads — 1yr History", "Refinery margins vs crude"),
            crack_row,
            sec_header("Context", ""),
            context,
        ])

    # ── GAS & LNG ─────────────────────────────────────────────────────────────
    elif tab == "gas":
        gas_names = ["Henry Hub (NG)", "Flex LNG", "Golar LNG"]
        price_cards = dbc.Row(
            [price_card(n, prices[n]) for n in gas_names if n in prices],
            style={"marginBottom": "20px"}
        )

        eia_gas_stor = fetch_eia("NW2ST_NUS_2", 104) if False else pd.DataFrame()

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=line_chart("NG=F", "Henry Hub Natural Gas — 1yr", C["teal"]),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=line_chart("NG=F", "Henry Hub — 5yr", C["teal"], "5y"),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=line_chart("FLNG", "Flex LNG (LNG shipping proxy)", C["accent"]),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=line_chart("GLNG", "Golar LNG (LNG midstream proxy)", C["purple"]),
                              config={"displayModeBar": False}), md=6),
        ], style={"marginBottom": "20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("TTF vs Henry Hub vs JKM",
                         "Three gas benchmarks: TTF (European, €/MWh), Henry Hub (US, $/MMBtu), "
                         "JKM (Asian LNG spot, $/MMBtu). "
                         "US LNG goes east if JKM > Henry Hub + $3 liquefaction + freight. "
                         "Goes to Europe if TTF > JKM + freight. The spread drives global LNG routing.", C["teal"]),
                info_box("European Gas Storage",
                         "GIE AGSI data — % full vs seasonal norms. "
                         "EU winter target ~90% full. Summer injection season April-October. "
                         "Storage deficit = TTF bullish. Currently post-winter draw, "
                         "injection season underway. Russian pipeline gas now minimal — "
                         "Europe structurally dependent on LNG and Norwegian supply.", C["amber"]),
            ], md=6),
            dbc.Col([
                info_box("LNG Trade Flows",
                         "US now world's largest LNG exporter (~14 bcf/d). "
                         "Key exporters: US, Qatar, Australia, Russia (Sakhalin, Arctic). "
                         "Key importers: Japan, China, South Korea, Europe. "
                         "Cold snap in NE Asia spikes JKM $3-5 in days — diverts Atlantic cargoes.", C["accent"]),
                info_box("Seasonal Patterns",
                         "Gas demand peaks: winter heating (Dec-Feb) and summer power (Jul-Aug). "
                         "Spring/autumn shoulder season = weakest demand, storage injection. "
                         "European summer 2024 storage filled fast → TTF weak into autumn. "
                         "Watch weather forecasts 2 weeks out — biggest short-term price driver.", C["green"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Natural Gas & LNG", "Henry Hub, TTF, JKM, LNG trade flows"),
            price_cards,
            sec_header("Price History", ""),
            charts,
            sec_header("Fundamental Context", ""),
            context,
        ])

    # ── FREIGHT ───────────────────────────────────────────────────────────────
    elif tab == "freight":
        freight_names = list(FREIGHT_TICKERS.keys())
        price_cards = dbc.Row(
            [price_card(n, prices[n]) for n in freight_names if n in prices],
            style={"marginBottom": "20px"}
        )

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=line_chart("EURN", "Euronav — VLCC proxy (1yr)", C["accent"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("FRO",  "Frontline — tanker proxy (1yr)", C["teal"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("BDRY", "BDRY — Baltic Dry ETF (1yr)", C["amber"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("FLNG", "Flex LNG — LNG shipping (1yr)", C["purple"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("DHT",  "DHT Holdings — VLCC (1yr)", C["green"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("BOAT", "Global Ship ETF (1yr)", C["muted"]),
                              config={"displayModeBar": False}), md=4),
        ], style={"marginBottom": "20px"})

        routes = [
            ("TD3C — VLCC",    C["accent"],  "Middle East Gulf → China (2mb cargo). Benchmark VLCC route. "
             "Rates driven by OPEC+ export volumes and Chinese crude demand. "
             "High WS = tight tonnage = bullish crude demand signal."),
            ("TD20 — Suezmax", C["teal"],   "West Africa → Continent. Key for Nigerian/Angolan crude "
             "into European refineries. Rates rise when Atlantic basin is flowing strongly."),
            ("TC2 — MR Tanker",C["amber"],  "Rotterdam → USAC. Clean products (gasoline, naphtha). "
             "Tight TC2 rates signal strong transatlantic product arbitrage."),
            ("LNG Shipping",   C["purple"], "Spot day rates for LNG carriers (~$40-180k/day range). "
             "Spike in winter on NE Asia demand. Low in summer shoulder season. "
             "Flex LNG and Golar are listed proxies."),
            ("Baltic Dry BDI", C["green"],  "Dry bulk: iron ore, coal, grain. Capesize (iron ore/coal), "
             "Panamax (grain/coal), Supramax. BDI as global industrial demand barometer."),
            ("Shadow Fleet",   C["red"],    "~600-700 vessels carrying Russian/Iranian/Venezuelan crude. "
             "Absorbs global tanker capacity. When utilisation rises, mainstream freight tightens. "
             "Track via Kpler/Vortexa AIS data."),
        ]

        route_cards = dbc.Row([
            dbc.Col(info_box(title, body, col), md=6)
            for title, col, body in routes
        ])

        return html.Div([
            sec_header("Freight & Shipping", "Tanker rates, dry bulk, LNG shipping — listed proxies"),
            price_cards,
            sec_header("Shipping Equity Proxies — 1yr", ""),
            charts,
            sec_header("Key Routes & Signals", ""),
            route_cards,
        ])

    # ── MACRO & METALS ────────────────────────────────────────────────────────
    elif tab == "macro":
        macro_names = list(MACRO_TICKERS.keys())
        price_cards = dbc.Row(
            [price_card(n, prices[n]) for n in macro_names if n in prices],
            style={"marginBottom": "20px"}
        )

        charts = dbc.Row([
            dbc.Col(dcc.Graph(figure=line_chart("DX-Y.NYB", "DXY (USD Index) — 1yr", C["amber"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("GC=F", "Gold — 1yr", C["amber"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("HG=F", "Copper — 1yr", C["teal"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("^TNX", "US 10Y Yield — 1yr", C["red"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("^VIX",   "VIX — 1yr", C["purple"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=line_chart("XLE",    "XLE Energy ETF — 1yr", C["green"]),
                              config={"displayModeBar": False}), md=4),
            dbc.Col(dcc.Graph(figure=spread_chart("HG=F", "GC=F", "Copper/Gold Ratio (×100)",
                                                   multiplier_a=100.0),
                              config={"displayModeBar": False}), md=6),
            dbc.Col(dcc.Graph(figure=line_chart("XOP", "XOP Oil & Gas ETF — 1yr", C["accent"]),
                              config={"displayModeBar": False}), md=6),
        ], style={"marginBottom": "20px"})

        context = dbc.Row([
            dbc.Col([
                info_box("DXY & Commodities",
                         "Commodities priced in USD — strong dollar = higher cost for EM importers "
                         "= demand destruction. DXY and Brent have strong negative correlation. "
                         "Fed hiking cycle → strong DXY → commodity headwind. "
                         "Watch real yields (TIPS) — negative real yields are very bullish for commodities.", C["amber"]),
                info_box("Copper as Global Barometer",
                         "Copper demand is dominated by China (55% of global consumption). "
                         "Rising copper = China industrial activity picking up = bullish for oil demand. "
                         "Copper-gold ratio rising = risk-on / growth. Falling = growth fears. "
                         "China credit impulse (Total Social Financing) leads copper by 6-9 months.", C["teal"]),
            ], md=6),
            dbc.Col([
                info_box("Energy Equities vs Crude",
                         "XLE/XOP vs crude oil divergence is a useful signal. "
                         "Equities leading crude higher = market believes crude will rise (forward-looking). "
                         "Equities lagging crude = equity market sceptical of commodity move. "
                         "HY energy credit spreads give you the market's implied floor oil price.", C["green"]),
                info_box("VIX & Commodity Volatility",
                         "High VIX = risk-off = institutional deleveraging = all assets sold. "
                         "In risk-off, commodities and equities correlate to 1. "
                         "After VIX spike and reversion, commodity vol term structure "
                         "often remains elevated — cheap to buy back-month options.", C["purple"]),
            ], md=6),
        ])

        return html.Div([
            sec_header("Macro & Metals", "DXY, yields, VIX, copper, gold, energy equities"),
            price_cards,
            sec_header("Charts — 1yr", ""),
            charts,
            sec_header("Inter-Market Signals", ""),
            context,
        ])

    # ── POSITIONING ───────────────────────────────────────────────────────────
    elif tab == "position":
        cot_df = fetch_cot()
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
            fig_net.add_trace(go.Bar(
                x=dates, y=net, marker_color=colors,
                hovertemplate="%{x|%b %d}: %{y:,.0f} contracts<extra></extra>",
            ))
            fig_net.add_hrect(y0=net_max * 0.85, y1=net_max,
                              fillcolor=C["red"], opacity=0.07,
                              annotation_text="Crowded long zone",
                              annotation_font_color=C["red"], annotation_font_size=10)
            fig_net.add_hrect(y0=net_min, y1=net_min * 0.85,
                              fillcolor=C["green"], opacity=0.07,
                              annotation_text="Crowded short zone",
                              annotation_font_color=C["green"], annotation_font_size=10)

            fig_gross.add_trace(go.Scatter(
                x=dates, y=longs.values.flatten(), mode="lines", name="Longs",
                line=dict(color=C["green"], width=1.8),
                hovertemplate="%{x|%b %d}: %{y:,.0f}<extra></extra>",
            ))
            fig_gross.add_trace(go.Scatter(
                x=dates, y=shorts.values.flatten(), mode="lines", name="Shorts",
                line=dict(color=C["red"], width=1.8),
                hovertemplate="%{x|%b %d}: %{y:,.0f}<extra></extra>",
            ))

            signal_col = (C["red"]   if net_pct > 75 else
                          C["green"] if net_pct < 25 else C["amber"])
            signal_txt = ("⚠ Crowded long — reversal risk high"    if net_pct > 75 else
                          "⚠ Crowded short — squeeze risk high"     if net_pct < 25 else
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
            html.Div(signal_txt, style={"fontSize": "15px", "fontWeight": "700",
                                         "color": signal_col}),
            html.Div(
                f"Net position: {latest_net:+,} contracts  |  "
                f"{net_pct}th percentile vs 1yr range",
                style={"fontSize": "12px", "color": C["muted"], "marginTop": "5px"},
            ),
        ], style={"background": C["card"], "border": f"1px solid {signal_col}44",
                  "borderLeft": f"3px solid {signal_col}", "borderRadius": "8px",
                  "padding": "14px 18px", "marginBottom": "18px"})

        context = dbc.Row([
            dbc.Col(info_box("How to Use the COT Report",
                             "CFTC Commitment of Traders released every Friday. "
                             "Shows managed money (hedge funds/CTAs) net positioning. "
                             "Extreme net long = crowded = reversal risk on any negative catalyst. "
                             "Extreme net short = squeeze risk. "
                             "Use as a crowding indicator, not a standalone entry signal.", C["accent"]), md=6),
            dbc.Col(info_box("Commercials vs Specs",
                             "Commercials (producers, refiners) are predominantly short — hedging production. "
                             "If commercials are COVERING shorts (reducing hedges), they see value at current prices. "
                             "This is the most bullish COT signal. "
                             "Swap dealers reflect institutional hedging demand — not directional.", C["amber"]), md=6),
        ])

        return html.Div([
            sec_header("Positioning & COT", "CFTC Commitment of Traders — managed money in WTI crude"),
            signal_card,
            dbc.Row([
                dbc.Col(dcc.Graph(figure=fig_net,   config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=fig_gross, config={"displayModeBar": False}), md=6),
            ], style={"marginBottom": "20px"}),
            context,
        ])

    # ── NEWS ──────────────────────────────────────────────────────────────────
    elif tab == "news":
        articles = fetch_news()
        if not articles:
            return html.Div("No news available — check network.",
                            style={"color": C["muted"], "padding": "20px"})
        cols = [[], [], []]
        for i, a in enumerate(articles):
            cols[i % 3].append(news_card(a))
        return html.Div([
            sec_header("Market News", "Live feeds from Reuters, EIA, FT, Platts"),
            dbc.Row([
                dbc.Col(cols[0], md=4),
                dbc.Col(cols[1], md=4),
                dbc.Col(cols[2], md=4),
            ]),
        ])

    return html.Div("Select a tab.", style={"color": C["muted"]})


# ── Run ───────────────────────────────────────────────────────────────────────
port = int(os.environ.get("PORT", 8050))
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=port)
