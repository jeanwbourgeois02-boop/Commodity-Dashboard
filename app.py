"""
Commodity Intelligence Dashboard
Real-time prices, spreads, freight signals, fundamentals & news
Run: python app.py  →  open http://localhost:8050
"""

import dash
from dash import dcc, html, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf
import pandas as pd
import requests
import feedparser
from datetime import datetime, timedelta
import json

# ── App init ─────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="Commodity Intelligence",
    update_title=None,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server

# ── Colour palette ────────────────────────────────────────────────────────────
C = {
    "bg":       "#0f1117",
    "surface":  "#1a1d27",
    "card":     "#21253a",
    "border":   "#2e3352",
    "accent":   "#4f6ef7",
    "green":    "#26c281",
    "red":      "#e05252",
    "amber":    "#f0a500",
    "text":     "#e8eaf6",
    "muted":    "#7b82a8",
    "teal":     "#20c9b0",
    "purple":   "#9b59b6",
}

# ── Ticker maps ───────────────────────────────────────────────────────────────
COMMODITIES = {
    "Brent Crude":        "BZ=F",
    "WTI Crude":          "CL=F",
    "Natural Gas":        "NG=F",
    "Gasoline (RBOB)":    "RB=F",
    "Heating Oil":        "HO=F",
    "Gold":               "GC=F",
    "Silver":             "SI=F",
    "Copper":             "HG=F",
    "Corn":               "ZC=F",
    "Wheat":              "ZW=F",
    "Soybeans":           "ZS=F",
    "Sugar #11":          "SB=F",
    "Coffee":             "KC=F",
    "Cotton":             "CT=F",
}

EQUITIES = {
    "S&P 500":          "^GSPC",
    "Energy ETF (XLE)": "XLE",
    "Oil & Gas (XOP)":  "XOP",
    "LNG (TANG)":       "TANG",
    "ExxonMobil":       "XOM",
    "Shell":            "SHEL",
    "BP":               "BP",
    "TotalEnergies":    "TTE",
    "Valero":           "VLO",
    "Marathon":         "MPC",
    "DXY Index":        "DX-Y.NYB",
    "Copper (COPX ETF)":"COPX",
}

MACRO = {
    "US 10Y Yield":     "^TNX",
    "VIX":              "^VIX",
    "EUR/USD":          "EURUSD=X",
    "USD/CNY":          "USDCNY=X",
    "USD/INR":          "USDINR=X",
}

FREIGHT_PROXY = {
    "Baltic Dry (BDI)":   "BDRY",   # Breakwave Dry Bulk ETF
    "Global Ship ETF":    "BOAT",
    "Euronav (VLCC)":     "EURN",
    "DHT Holdings":       "DHT",
    "Frontline":          "FRO",
    "Flex LNG":           "FLNG",
    "Golar LNG":          "GLNG",
}

NEWS_FEEDS = [
    ("Reuters Energy",       "https://feeds.reuters.com/reuters/businessNews"),
    ("FT Commodities",       "https://www.ft.com/commodities?format=rss"),
    ("S&P Global Platts",    "https://www.spglobal.com/commodityinsights/en/rss-feed/oil"),
    ("EIA News",             "https://www.eia.gov/rss/news.xml"),
    ("Bloomberg Energy",     "https://feeds.bloomberg.com/energy/news.rss"),
]

# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_prices(tickers: dict) -> list[dict]:
    symbols = list(tickers.values())
    try:
        data = yf.download(symbols, period="2d", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True)
    except Exception:
        return []

    rows = []
    for name, sym in tickers.items():
        try:
            if len(symbols) == 1:
                close = data["Close"].dropna()
            else:
                close = data[sym]["Close"].dropna()
            if len(close) < 1:
                continue
            price = float(close.iloc[-1])
            prev  = float(close.iloc[-2]) if len(close) >= 2 else price
            chg   = price - prev
            pct   = (chg / prev * 100) if prev else 0
            rows.append({"name": name, "sym": sym, "price": price,
                         "chg": chg, "pct": pct})
        except Exception:
            continue
    return rows


def fetch_history(sym: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
    try:
        df = yf.download(sym, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        return df[["Close"]].dropna().rename(columns={"Close": "price"})
    except Exception:
        return pd.DataFrame()


def fetch_curve(sym: str) -> list[dict]:
    """Fetch front 6 monthly contracts for a futures symbol to show curve shape."""
    suffixes = ["=F", "H25.NYM", "K25.NYM", "M25.NYM", "N25.NYM", "U25.NYM", "Z25.NYM"]
    base = sym.replace("=F", "")
    months = ["M1", "M2", "M3", "M4", "M5", "M6"]
    prices = []
    symbols_to_try = [sym]
    for s in [f"{base}M25.NYM", f"{base}N25.NYM", f"{base}U25.NYM",
              f"{base}V25.NYM", f"{base}X25.NYM", f"{base}Z25.NYM"]:
        symbols_to_try.append(s)

    for i, s in enumerate(symbols_to_try[:6]):
        try:
            t = yf.Ticker(s)
            hist = t.history(period="1d")
            if not hist.empty:
                prices.append({"month": months[i], "price": float(hist["Close"].iloc[-1])})
        except Exception:
            pass
    return prices


def fetch_news() -> list[dict]:
    articles = []
    for source, url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]:
                articles.append({
                    "source": source,
                    "title":  entry.get("title", ""),
                    "link":   entry.get("link", "#"),
                    "time":   entry.get("published", ""),
                })
        except Exception:
            pass
    return articles[:30]


def calc_spreads(rows: list[dict]) -> list[dict]:
    pm = {r["name"]: r["price"] for r in rows}
    spreads = []

    def add(label, a, b, unit="$/bbl", note=""):
        va = pm.get(a)
        vb = pm.get(b)
        if va and vb:
            v = va - vb
            spreads.append({"label": label, "value": v, "unit": unit, "note": note})

    add("Brent – WTI",     "Brent Crude",    "WTI Crude",
        note="Positive = Brent premium. Arb drives US crude exports.")
    add("Gasoline crack",  "Gasoline (RBOB)","WTI Crude",
        note="Higher crack = more refinery margin on gasoline. Seasonal.")
    add("Heat oil crack",  "Heating Oil",    "WTI Crude",
        note="Diesel/heating oil margin. Industrial demand barometer.")
    add("Copper – Gold ratio", "Copper", "Gold", unit="ratio x100",
        note="Rising = risk-on / growth expectations. Leads crude.")

    # Nat gas spread (TTF proxy via NG vs JKM—approximated)
    ng = pm.get("Natural Gas")
    if ng:
        spreads.append({"label": "Henry Hub NG ($/MMBtu)", "value": ng,
                        "unit": "$/MMBtu", "note": "US gas benchmark. Compare vs TTF (€/MWh) and JKM ($/MMBtu)."})
    return spreads


# ── Chart helpers ─────────────────────────────────────────────────────────────

def price_chart(sym: str, name: str, period: str = "3mo") -> go.Figure:
    df = fetch_history(sym, period=period)
    fig = go.Figure()
    if df.empty:
        fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False,
                           font=dict(color=C["muted"]))
    else:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["price"].values.flatten(),
            mode="lines", line=dict(color=C["accent"], width=1.8),
            fill="tozeroy", fillcolor="rgba(79,110,247,0.08)",
            hovertemplate="%{y:.2f}<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text=name, font=dict(size=13, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=32, b=8),
        xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=10)),
        height=180,
    )
    return fig


def curve_chart(sym: str, name: str) -> go.Figure:
    pts = fetch_curve(sym)
    fig = go.Figure()
    if len(pts) >= 2:
        xs = [p["month"] for p in pts]
        ys = [p["price"]  for p in pts]
        color = C["green"] if ys[0] >= ys[-1] else C["red"]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=6, color=color),
            hovertemplate="%{x}: %{y:.2f}<extra></extra>",
        ))
        struct = "Backwardation ↓" if ys[0] > ys[-1] else "Contango ↑"
        fig.add_annotation(text=struct, x=0.98, y=0.95, xref="paper",
                           yref="paper", showarrow=False,
                           font=dict(color=color, size=11))
    else:
        fig.add_annotation(text="Curve data unavailable", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=C["muted"]))
    fig.update_layout(
        title=dict(text=f"{name} – forward curve", font=dict(size=12, color=C["text"]), x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=32, b=8),
        xaxis=dict(showgrid=False, color=C["muted"]),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   tickfont=dict(size=10)),
        height=200,
    )
    return fig


def sector_heatmap(rows: list[dict]) -> go.Figure:
    if not rows:
        return go.Figure()
    names = [r["name"] for r in rows]
    pcts  = [round(r["pct"], 2) for r in rows]
    colors = [C["green"] if p >= 0 else C["red"] for p in pcts]
    fig = go.Figure(go.Bar(
        x=names, y=pcts,
        marker_color=colors,
        hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>",
        text=[f"{p:+.1f}%" for p in pcts],
        textposition="outside",
        textfont=dict(size=10, color=C["text"]),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=4, r=4, t=8, b=60),
        xaxis=dict(tickangle=-35, color=C["muted"], tickfont=dict(size=10), showgrid=False),
        yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                   zeroline=True, zerolinecolor=C["border"], tickfont=dict(size=10)),
        height=240,
        showlegend=False,
    )
    return fig


# ── UI helpers ────────────────────────────────────────────────────────────────

def badge(label: str, color: str = C["muted"]) -> html.Span:
    return html.Span(label, style={
        "background": color + "22", "color": color,
        "borderRadius": "4px", "padding": "2px 7px",
        "fontSize": "11px", "marginRight": "4px",
    })


def metric_card(name: str, price: float, chg: float, pct: float,
                sym: str = "") -> dbc.Col:
    up = pct >= 0
    arrow = "▲" if up else "▼"
    col = C["green"] if up else C["red"]
    return dbc.Col(
        html.Div([
            html.Div(name, style={"fontSize": "11px", "color": C["muted"],
                                  "marginBottom": "4px", "fontWeight": "500"}),
            html.Div(f"{price:,.2f}", style={"fontSize": "20px",
                                             "color": C["text"], "fontWeight": "600"}),
            html.Div(f"{arrow} {abs(pct):.2f}%  ({chg:+.2f})",
                     style={"fontSize": "12px", "color": col, "marginTop": "3px"}),
        ], style={
            "background": C["card"], "border": f"1px solid {C['border']}",
            "borderRadius": "8px", "padding": "12px 14px",
        }),
        xs=6, sm=4, md=3, lg=2, style={"marginBottom": "10px"},
    )


def spread_row(s: dict) -> html.Div:
    v = s["value"]
    col = C["green"] if v >= 0 else C["red"]
    sign = "+" if v >= 0 else ""
    return html.Div([
        html.Div([
            html.Span(s["label"], style={"color": C["text"], "fontSize": "13px",
                                         "fontWeight": "500"}),
            html.Span(f"  {sign}{v:.2f} {s['unit']}",
                      style={"color": col, "fontSize": "13px", "marginLeft": "8px"}),
        ]),
        html.Div(s.get("note", ""), style={"fontSize": "11px", "color": C["muted"],
                                            "marginTop": "2px"}),
    ], style={"borderBottom": f"1px solid {C['border']}",
              "padding": "8px 0"})


def news_card(a: dict) -> html.Div:
    return html.Div([
        html.Div(a["source"], style={"fontSize": "10px", "color": C["accent"],
                                      "fontWeight": "600", "marginBottom": "3px"}),
        html.A(a["title"], href=a["link"], target="_blank",
               style={"color": C["text"], "fontSize": "12px",
                      "textDecoration": "none",
                      "display": "block", "lineHeight": "1.4"}),
        html.Div(a.get("time", ""), style={"fontSize": "10px",
                                            "color": C["muted"], "marginTop": "3px"}),
    ], style={
        "background": C["card"], "border": f"1px solid {C['border']}",
        "borderRadius": "6px", "padding": "10px 12px", "marginBottom": "8px",
    })


# ── Participant profiles (static knowledge) ───────────────────────────────────

PARTICIPANT_DATA = {
    "commodity": [
        {
            "role": "National Oil Companies (NOCs)",
            "examples": "Saudi Aramco, ADNOC, NIOC, Rosneft, PDVSA",
            "what": "State-owned producers. Sell crude via term contracts. Set Official Selling Prices (OSPs) monthly — the single most important pricing signal for Middle East crude flows into Asia.",
            "cares": ["OSP differentials vs market", "OPEC quota / market share", "Long-term offtake security", "Geopolitical mandate"],
            "color": C["amber"],
        },
        {
            "role": "Independent Trading Houses",
            "examples": "Vitol, Trafigura, Glencore, Gunvor, Mercuria",
            "what": "The merchants of commodity markets. Move physical cargoes globally. Profit from logistics, quality, time and geographical arbitrages. Enormous balance sheets and global information networks. If price is anywhere wrong, they find it.",
            "cares": ["Physical arb windows", "Storage economics / contango", "Freight rates", "Credit / counterparty risk", "Sanctions compliance"],
            "color": C["teal"],
        },
        {
            "role": "Refiners",
            "examples": "Valero, Marathon, Petroineos, ENEOS, Reliance",
            "what": "Buy crude, sell products. Continuously optimise their crude slate — choosing the cheapest crude that runs through their specific kit. Hedge crack spread margins. Buy crude 30–60 days before running.",
            "cares": ["Crack spread level", "Crude quality vs product yield", "Freight to refinery gate", "Product demand outlook", "Regulatory specs (IMO, CAFE)"],
            "color": C["purple"],
        },
        {
            "role": "Commodity Hedge Funds",
            "examples": "Andurand Capital, Citadel Commodities, Hartree Partners, Millennium energy",
            "what": "Take directional and relative value positions. Combine fundamental analysis with positioning/flow awareness. Fast to cut risk — can amplify moves in both directions. Andurand-style macro funds overlay geopolitics and demand modelling.",
            "cares": ["Supply/demand balance", "Positioning (COT)", "Technical levels", "Macro correlation (DXY, PMI)", "Geopolitical risk premium"],
            "color": C["accent"],
        },
        {
            "role": "Airlines & Industrial End-Users",
            "examples": "IAG, Delta, Lufthansa, large shipping co's",
            "what": "Hedge fuel cost exposure using jet fuel swaps, crude options, bunker hedges. Predominantly buyers of calls or call spreads — creating structural demand for upside optionality in crude and jet.",
            "cares": ["Cost certainty over budget horizon", "Hedge ratio vs competitors", "Fuel surcharge pass-through", "Break-even oil price"],
            "color": C["green"],
        },
        {
            "role": "Commodity Index Funds (Passive)",
            "examples": "GSCI trackers, Bloomberg Commodity Index funds",
            "what": "Pension funds tracking commodity indices. Roll positions monthly on fixed schedules — creates predictable roll bleed in contango. Rebalance seasonally creating temporary price distortions. Not alpha-seeking — pure exposure.",
            "cares": ["Index composition & weights", "Roll schedule efficiency", "Correlation to equity portfolio", "Inflation hedge properties"],
            "color": C["muted"],
        },
    ],
    "equity": [
        {
            "role": "Long-Only Asset Managers",
            "examples": "BlackRock, Vanguard, Fidelity, Capital Group, Wellington",
            "what": "Manage trillions. Benchmark-aware — performance is judged vs S&P 500 or MSCI World. Their large block trades move stocks for days. Quarterly rebalancing creates seasonal patterns. ESG screens increasingly exclude fossil fuel producers.",
            "cares": ["Earnings growth vs consensus", "Valuation vs benchmark peers", "Index inclusion/exclusion", "ESG screens", "Factor exposure (quality, growth, value)"],
            "color": C["accent"],
        },
        {
            "role": "Equity Hedge Funds (L/S)",
            "examples": "Tiger Global, Coatue, D1, Point72, Millennium",
            "what": "Long/short equity. Alpha vs beta. Care about factor neutrality, gross/net exposure, and catalyst timing. Event-driven funds (Elliott, Third Point) take activist positions. All care about liquidity when risk-off — their simultaneous exit worsens dislocations.",
            "cares": ["Alpha vs benchmark beta", "Factor exposure (momentum, value, size)", "Short interest / borrow cost", "Catalyst timing", "Prime broker leverage limits"],
            "color": C["teal"],
        },
        {
            "role": "HFT / Market Makers",
            "examples": "Citadel Securities, Virtu, Jane Street, Jump Trading",
            "what": "Provide liquidity and arbitrage prices across venues in microseconds. Not directional — profit from spread capture and inventory management. Their withdrawal during stress events worsens liquidity crises. Jane Street dominates ETF market-making.",
            "cares": ["Bid-ask spread capture", "Adverse selection (toxic flow)", "Latency vs competitors", "Exchange fee structure", "Inventory risk"],
            "color": C["amber"],
        },
        {
            "role": "Systematic / Quant Funds",
            "examples": "Renaissance, Two Sigma, DE Shaw, Man AHL, Winton",
            "what": "Trade statistical patterns, factor models, alternative data. CTAs trend-follow across asset classes. Their positioning can be estimated from factor crowding and momentum signals. Amplify moves when all running same model.",
            "cares": ["Signal decay / alpha half-life", "Factor crowding risk", "Execution / market impact", "Alternative data edge", "Capacity constraints"],
            "color": C["purple"],
        },
        {
            "role": "Retail & Options-Driven Flow",
            "examples": "Robinhood users, Reddit communities, zero-commission options traders",
            "what": "Post-2020 phenomenon. 0DTE options, meme stocks, social media coordination. Can create gamma squeezes when dealers are short gamma and hedge by buying stock. Biggest impact in small caps and heavily optioned mega caps (NVDA, TSLA).",
            "cares": ["Social media sentiment", "Short squeeze potential (short float %)", "Options gamma positioning", "Momentum / attention"],
            "color": C["red"],
        },
        {
            "role": "Sovereign Wealth Funds",
            "examples": "Norges Bank (NBIM), GIC, Temasek, ADIA, Saudi PIF",
            "what": "Enormous long-term holders. NBIM owns ~1.5% of all listed equities globally. Quarterly rebalancing is significant. Some SWFs are activist (PIF). Patient capital but flows large enough to move markets when disclosed.",
            "cares": ["Long-term real return", "Liability matching", "Geopolitical exposure limits", "ESG and governance", "Home country investment mandates"],
            "color": C["green"],
        },
    ],
}


def participant_card(p: dict) -> html.Div:
    col = p["color"]
    return html.Div([
        html.Div(p["role"], style={"fontSize": "13px", "fontWeight": "600",
                                    "color": col, "marginBottom": "3px"}),
        html.Div(p["examples"], style={"fontSize": "11px", "color": C["muted"],
                                        "marginBottom": "6px", "fontStyle": "italic"}),
        html.Div(p["what"], style={"fontSize": "12px", "color": C["text"],
                                    "lineHeight": "1.5", "marginBottom": "8px"}),
        html.Div(
            [badge(c, col) for c in p["cares"]],
            style={"flexWrap": "wrap", "display": "flex", "gap": "4px"}
        ),
    ], style={
        "background": C["card"],
        "border": f"1px solid {col}44",
        "borderLeft": f"3px solid {col}",
        "borderRadius": "6px",
        "padding": "12px 14px",
        "marginBottom": "10px",
    })


# ── Sections ──────────────────────────────────────────────────────────────────

def section_header(title: str, subtitle: str = "") -> html.Div:
    return html.Div([
        html.H5(title, style={"color": C["text"], "margin": "0 0 2px 0",
                               "fontWeight": "600"}),
        html.Div(subtitle, style={"color": C["muted"], "fontSize": "12px"}),
    ], style={"borderLeft": f"3px solid {C['accent']}", "paddingLeft": "10px",
              "marginBottom": "16px"})


MARKET_STRUCTURE_TEXT = {
    "Contango vs Backwardation": {
        "color": C["teal"],
        "body": """
**Backwardation** — spot price > futures price. Market signals tight near-term supply or strong demand. Physical holders earn "roll yield." Incentivises drawing down storage. Bullish structural signal — the physical market is hungry now.

**Contango** — futures > spot. Incentivises storing the commodity and selling it forward. Storage operators and tanker owners benefit. Long futures holders pay "roll cost" each month. Common in oversupplied markets.

**The time spread** (M1 minus M2) is the most-watched structural signal in oil. A backwardated time spread is the best single confirmation of physical tightness.
        """,
    },
    "Physical vs Paper": {
        "color": C["amber"],
        "body": """
**Paper** — ICE Brent futures, CME WTI, CME Henry Hub. Cash/financially settled. 95%+ of futures never result in physical delivery. Used for hedging and speculation. Price discovery happens here.

**Physical** — actual cargo transactions. Assessed by Platts and Argus to produce benchmark prices (Dated Brent, Oman, HSFO Singapore). Physical traders need shipping, credit lines, storage, and blending expertise.

**The connection** — Physical prices anchor the paper market. When physical is tight, the paper curve backs up. The EFP (Exchange for Physical) and EFS (Exchange for Swaps) are the bridge mechanisms.

**Dated Brent** is set in the Platts Price Window — a 15-minute daily window (4:00–4:30pm London) where cargoes are bid and offered. These trades set the world oil price.
        """,
    },
    "COT Report — Reading Positioning": {
        "color": C["purple"],
        "body": """
The CFTC **Commitment of Traders** report (released every Friday) shows who holds what in futures markets.

**Managed money (specs)** — hedge funds and CTAs. Trend-follow and take directional views. When extremely net long → crowded trade, reversal risk. When at multi-year net short extreme → contrarian buy signal.

**Producer/merchant (commercials)** — oil companies, refiners, airlines. Hedge real exposure. Predominantly short (hedging production). If commercials are *covering* shorts → they see value at current prices. Smart money signal.

**Swap dealers** — banks. Reflect institutional hedging demand rather than directional views.

**Key rule**: COT is a positioning indicator, not a timing signal. Extremes can persist for weeks. Use it to assess crowding risk, not as a standalone entry trigger.
        """,
    },
    "Crack Spreads — Refinery Economics": {
        "color": C["green"],
        "body": """
Crack spreads measure the profit margin from refining crude into products.

**3-2-1 crack** = (2 × gasoline price + 1 × diesel price − 3 × crude price) / 3. The standard US refinery margin metric.

**Gasoline crack** — highest in US driving season (May–September). Signals consumer fuel demand.

**Jet/kero crack** — reflects aviation demand recovery. Now the strongest product crack globally as jet demand rebounds.

**Fuel oil crack** — negative (fuel oil < crude cost). Refiners want to minimise fuel oil yield. Low-sulphur fuel oil (LSFO) premium over HSFO driven by IMO 2020.

High cracks attract more crude runs → supports crude demand → bullish crude. The feedback loop is real.
        """,
    },
    "Freight as a Market Signal": {
        "color": C["red"],
        "body": """
Freight rates are not just a cost — they're a **real-time signal of physical market tightness**.

**Rising VLCC rates** signal: more crude is moving; Middle East-to-Asia demand is strong; tonne-miles are increasing (longer voyages). Can signal Chinese restocking or OPEC export surge.

**Falling VLCC rates** signal: crude moving less; exports declining; refinery maintenance season; Chinese imports slowing.

**The EFS-freight relationship**: High VLCC rates can close the Brent-Dubai EFS arbitrage (makes it more expensive to ship cheap ME crude to Asia, so ME crude needs to widen its discount to Brent further).

**Shadow fleet**: ~600-700 vessels carrying Russian, Iranian, Venezuelan crude. Opaque tracking — but when shadow fleet utilisation rises, it absorbs capacity from the global market, tightening mainstream freight.
        """,
    },
}


def structure_card(title: str, info: dict) -> html.Div:
    col = info["color"]
    lines = [l for l in info["body"].strip().split("\n") if l.strip()]
    content = []
    for line in lines:
        if line.startswith("**") and line.endswith("**"):
            content.append(html.Div(line.strip("*"), style={
                "fontWeight": "600", "color": col, "fontSize": "13px",
                "marginTop": "8px",
            }))
        else:
            # handle inline bold
            parts = line.split("**")
            span_els = []
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    span_els.append(html.Strong(part, style={"color": col}))
                else:
                    span_els.append(part)
            content.append(html.P(span_els, style={"fontSize": "12px",
                                                    "color": C["text"],
                                                    "lineHeight": "1.6",
                                                    "margin": "4px 0"}))
    return html.Div([
        html.Div(title, style={"fontSize": "14px", "fontWeight": "700",
                                "color": col, "marginBottom": "10px"}),
        html.Div(content),
    ], style={
        "background": C["card"],
        "border": f"1px solid {col}44",
        "borderLeft": f"3px solid {col}",
        "borderRadius": "6px",
        "padding": "14px 16px",
        "marginBottom": "12px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────

NAV_STYLE = {
    "background": C["surface"],
    "borderBottom": f"1px solid {C['border']}",
    "padding": "0 20px",
    "position": "sticky",
    "top": "0",
    "zIndex": "100",
}

TAB_STYLE = {
    "color": C["muted"],
    "backgroundColor": "transparent",
    "border": "none",
    "padding": "14px 18px",
    "fontSize": "13px",
    "fontWeight": "500",
}

TAB_SELECTED = {
    "color": C["accent"],
    "backgroundColor": "transparent",
    "border": "none",
    "borderBottom": f"2px solid {C['accent']}",
    "padding": "14px 18px",
    "fontSize": "13px",
    "fontWeight": "600",
}

app.layout = html.Div(style={"background": C["bg"], "minHeight": "100vh",
                              "fontFamily": "'Inter', 'Segoe UI', sans-serif"}, children=[

    # ── Header ────────────────────────────────────────────────────────────────
    html.Div([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Span("◈ ", style={"color": C["accent"], "fontSize": "18px"}),
                    html.Span("COMMODITY INTELLIGENCE", style={
                        "color": C["text"], "fontSize": "15px",
                        "fontWeight": "700", "letterSpacing": "2px",
                    }),
                ]),
            ], width="auto"),
            dbc.Col([
                html.Div(id="last-updated", style={"color": C["muted"],
                                                    "fontSize": "11px",
                                                    "textAlign": "right",
                                                    "paddingTop": "4px"}),
            ]),
            dbc.Col([
                dbc.Button("↻ Refresh", id="refresh-btn", size="sm",
                           style={"background": C["accent"] + "22",
                                  "border": f"1px solid {C['accent']}55",
                                  "color": C["accent"], "fontSize": "12px",
                                  "borderRadius": "6px"}),
            ], width="auto"),
        ], align="center", style={"padding": "12px 0"}),
    ], style=NAV_STYLE),

    # ── Tabs ──────────────────────────────────────────────────────────────────
    html.Div([
        dcc.Tabs(id="main-tabs", value="prices",
                 style={"background": C["surface"],
                        "borderBottom": f"1px solid {C['border']}"},
                 children=[
            dcc.Tab(label="Prices & Spreads",  value="prices",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="Charts",            value="charts",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="Freight & Flows",   value="freight",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="Market Structure",  value="structure",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="Participants",      value="participants",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="News",              value="news",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="EIA Inventories",   value="eia",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="COT Positioning",   value="cot",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
            dcc.Tab(label="Crack Spreads",     value="cracks",
                    style=TAB_STYLE, selected_style=TAB_SELECTED),
        ]),
        
    ]),

    # ── Content ───────────────────────────────────────────────────────────────
    html.Div(id="tab-content", style={"padding": "20px 24px"}),

    # ── Interval refresh ─────────────────────────────────────────────────────
    dcc.Interval(id="auto-refresh", interval=300_000, n_intervals=0),  # 5 min
    dcc.Store(id="price-store"),
])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("price-store", "data"),
    Output("last-updated", "children"),
    Input("auto-refresh", "n_intervals"),
    Input("refresh-btn",  "n_clicks"),
)
def update_store(_, __):
    all_tickers = {**COMMODITIES, **EQUITIES, **MACRO, **FREIGHT_PROXY}
    rows = fetch_prices(all_tickers)
    ts = datetime.utcnow().strftime("Updated %H:%M UTC")
    return rows, ts


@app.callback(
    Output("tab-content", "children"),
    Input("main-tabs",   "value"),
    Input("price-store", "data"),
)
def render_tab(tab, data):
    data = data or []
    comm_rows    = [r for r in data if r["name"] in COMMODITIES]
    equity_rows  = [r for r in data if r["name"] in EQUITIES]
    macro_rows   = [r for r in data if r["name"] in MACRO]
    freight_rows = [r for r in data if r["name"] in FREIGHT_PROXY]
    spreads      = calc_spreads(comm_rows)

    # ── PRICES & SPREADS ──────────────────────────────────────────────────────
    if tab == "prices":
        comm_cards = dbc.Row([
            metric_card(r["name"], r["price"], r["chg"], r["pct"])
            for r in comm_rows
        ], style={"marginBottom": "20px"})

        eq_cards = dbc.Row([
            metric_card(r["name"], r["price"], r["chg"], r["pct"])
            for r in equity_rows
        ], style={"marginBottom": "20px"})

        macro_cards = dbc.Row([
            metric_card(r["name"], r["price"], r["chg"], r["pct"])
            for r in macro_rows
        ], style={"marginBottom": "20px"})

        spread_section = html.Div([
            html.Div([spread_row(s) for s in spreads]),
        ], style={
            "background": C["card"],
            "border": f"1px solid {C['border']}",
            "borderRadius": "8px",
            "padding": "14px 18px",
        })

        heatmap = dcc.Graph(
            figure=sector_heatmap(comm_rows + equity_rows),
            config={"displayModeBar": False},
        )

        return html.Div([
            section_header("Commodities", "Real-time futures prices"),
            comm_cards,
            section_header("Equities & ETFs", "Energy sector, macro proxies"),
            eq_cards,
            section_header("Macro Signals", "Rates, FX, volatility"),
            macro_cards,
            dbc.Row([
                dbc.Col([
                    section_header("Key Spreads", "Calculated from live prices"),
                    spread_section,
                ], md=5),
                dbc.Col([
                    section_header("Daily Performance", "% change today"),
                    heatmap,
                ], md=7),
            ]),
        ])

    # ── CHARTS ────────────────────────────────────────────────────────────────
    elif tab == "charts":
        key_charts = [
            ("BZ=F",  "Brent Crude"),
            ("CL=F",  "WTI Crude"),
            ("NG=F",  "Natural Gas (Henry Hub)"),
            ("HG=F",  "Copper"),
            ("GC=F",  "Gold"),
            ("RB=F",  "Gasoline RBOB"),
        ]
        price_charts = dbc.Row([
            dbc.Col(
                dcc.Graph(figure=price_chart(sym, name),
                          config={"displayModeBar": False}),
                md=4, style={"marginBottom": "12px"}
            )
            for sym, name in key_charts
        ])

        curve_charts = dbc.Row([
            dbc.Col(
                dcc.Graph(figure=curve_chart("BZ=F", "Brent"),
                          config={"displayModeBar": False}),
                md=6,
            ),
            dbc.Col(
                dcc.Graph(figure=curve_chart("CL=F", "WTI"),
                          config={"displayModeBar": False}),
                md=6,
            ),
        ])

        return html.Div([
            section_header("Price History", "3-month rolling window"),
            price_charts,
            section_header("Forward Curves", "Contango vs backwardation structure"),
            curve_charts,
        ])

    # ── FREIGHT ───────────────────────────────────────────────────────────────
    elif tab == "freight":
        freight_cards = dbc.Row([
            metric_card(r["name"], r["price"], r["chg"], r["pct"])
            for r in freight_rows
        ], style={"marginBottom": "20px"})

        freight_info = [
            ("VLCC (TD3C)", C["amber"],
             "Middle East Gulf → China. 2m bbl cargo. Rates driven by OPEC+ export volumes, "
             "Chinese demand, and fleet utilisation. Benchmark proxy: Euronav (EURN), DHT, Frontline (FRO)."),
            ("Suezmax (TD20)", C["teal"],
             "West Africa → Continent. Key for Nigerian/Angolan crude into European refineries. "
             "Rates rise when Atlantic basin crude flows strongly westward."),
            ("LNG Shipping", C["accent"],
             "Spot day rates for LNG carriers. Flex LNG (FLNG) and Golar LNG (GLNG) are listed proxies. "
             "Rates spike in winter on NE Asia demand. Low in summer. TTF-JKM spread drives routing decisions."),
            ("Baltic Dry (BDI)", C["green"],
             "Dry bulk: iron ore, coal, grain. BDRY ETF tracks Capesize/Panamax/Supramax rates. "
             "BDI as a global industrial demand barometer — but noisy short-term."),
            ("Shadow Fleet Signal", C["red"],
             "~600-700 vessels carrying Russian/Iranian/Venezuelan crude. Absorbs global tanker capacity. "
             "When shadow fleet utilisation rises, mainstream freight tightens. Track via Kpler AIS data."),
        ]

        info_cards = html.Div([
            html.Div([
                html.Div(title, style={"fontSize": "13px", "fontWeight": "600",
                                        "color": col, "marginBottom": "5px"}),
                html.Div(body, style={"fontSize": "12px", "color": C["text"],
                                       "lineHeight": "1.5"}),
            ], style={
                "background": C["card"],
                "border": f"1px solid {col}44",
                "borderLeft": f"3px solid {col}",
                "borderRadius": "6px",
                "padding": "12px 14px",
                "marginBottom": "10px",
            })
            for title, col, body in freight_info
        ])

        flow_routes = html.Div([
            html.Div("Major crude trade routes", style={
                "fontSize": "13px", "fontWeight": "600",
                "color": C["text"], "marginBottom": "12px",
            }),
            *[
                html.Div([
                    html.Div([
                        html.Span(origin, style={"background": C["accent"] + "22",
                                                  "color": C["accent"],
                                                  "borderRadius": "4px",
                                                  "padding": "3px 8px",
                                                  "fontSize": "11px"}),
                        html.Span(" → ", style={"color": C["muted"]}),
                        html.Span(dest, style={"background": C["teal"] + "22",
                                                "color": C["teal"],
                                                "borderRadius": "4px",
                                                "padding": "3px 8px",
                                                "fontSize": "11px"}),
                        html.Span(f"  {vessel}", style={"color": C["muted"],
                                                         "fontSize": "11px",
                                                         "marginLeft": "8px"}),
                    ]),
                    html.Div(note, style={"fontSize": "11px", "color": C["muted"],
                                          "marginTop": "3px", "marginBottom": "10px"}),
                ])
                for origin, dest, vessel, note in [
                    ("Middle East Gulf", "China/Asia", "VLCC 2Mb",
                     "TD3C benchmark. OPEC+ cuts reduce this flow. Chinese teapot demand drives volumes."),
                    ("US Gulf", "NWE / Asia", "VLCC / Suezmax",
                     "WTI Midland exports. Flow driven by Brent-WTI spread vs freight economics."),
                    ("West Africa", "Europe / Asia", "Suezmax / Aframax",
                     "Nigerian Bonny Light, Angolan Girassol. TD20 benchmark. Spot-driven."),
                    ("North Sea", "Global (spot)", "Aframax",
                     "Brent, Forties, Oseberg, Ekofisk, Troll — the BFOET basket underpinning Dated Brent."),
                    ("Russia (shadow)", "India / China", "VLCC / Suezmax",
                     "Post-sanction rerouting. Urals at deep discount to Brent. Track via AIS / Kpler."),
                    ("US Gulf (LNG)", "Europe / NE Asia", "LNG carrier",
                     "Atlantic vs Pacific routing driven by TTF vs JKM spread minus freight + liquefaction."),
                ]
            ],
        ], style={
            "background": C["card"],
            "border": f"1px solid {C['border']}",
            "borderRadius": "8px",
            "padding": "16px",
        })

        return html.Div([
            section_header("Freight Proxies", "Listed equity proxies for shipping markets"),
            freight_cards,
            dbc.Row([
                dbc.Col([info_cards], md=6),
                dbc.Col([flow_routes], md=6),
            ]),
        ])

    # ── MARKET STRUCTURE ──────────────────────────────────────────────────────
    elif tab == "structure":
        cards = [structure_card(t, info)
                 for t, info in MARKET_STRUCTURE_TEXT.items()]
        mid = len(cards) // 2
        return html.Div([
            section_header("Market Structure", "Mechanics, curve dynamics, positioning frameworks"),
            dbc.Row([
                dbc.Col(cards[:mid + 1], md=6),
                dbc.Col(cards[mid + 1:], md=6),
            ]),
        ])

    # ── PARTICIPANTS ──────────────────────────────────────────────────────────
    elif tab == "participants":
        comm_cards   = [participant_card(p) for p in PARTICIPANT_DATA["commodity"]]
        equity_cards = [participant_card(p) for p in PARTICIPANT_DATA["equity"]]
        mid_c = len(comm_cards) // 2
        mid_e = len(equity_cards) // 2
        return html.Div([
            section_header("Commodity Market Participants", "Who they are, what they trade, what they optimise for"),
            dbc.Row([
                dbc.Col(comm_cards[:mid_c + 1], md=6),
                dbc.Col(comm_cards[mid_c + 1:], md=6),
            ]),
            html.Hr(style={"borderColor": C["border"], "margin": "24px 0"}),
            section_header("Equity Market Participants", "Order flow, microstructure, and who moves prices"),
            dbc.Row([
                dbc.Col(equity_cards[:mid_e + 1], md=6),
                dbc.Col(equity_cards[mid_e + 1:], md=6),
            ]),
        ])

    # ── NEWS ──────────────────────────────────────────────────────────────────
    elif tab == "news":
        articles = fetch_news()
        if not articles:
            return html.Div("No news fetched — check network / RSS feed availability.",
                            style={"color": C["muted"], "padding": "20px"})
        cols = [[], [], []]
        for i, a in enumerate(articles):
            cols[i % 3].append(news_card(a))
        return html.Div([
            section_header("Market News", "Live RSS feeds from Reuters, EIA, FT, Platts"),
            dbc.Row([
                dbc.Col(cols[0], md=4),
                dbc.Col(cols[1], md=4),
                dbc.Col(cols[2], md=4),
            ]),
        ])

    return html.Div("Select a tab", style={"color": C["muted"]})
    # ── EIA INVENTORIES ───────────────────────────────────────────────────────
    elif tab == "eia":
        inv = fetch_eia_inventories()

        def inv_chart(key, label):
            df = inv.get(key, pd.DataFrame())
            fig = go.Figure()
            if df.empty:
                fig.add_annotation(text="Loading EIA data...", x=0.5, y=0.5,
                                   showarrow=False, font=dict(color=C["muted"]))
            else:
                df2 = df.tail(52).copy()
                fig.add_trace(go.Scatter(
                    x=df2["period"], y=df2["value"],
                    mode="lines", name="Actual",
                    line=dict(color=C["accent"], width=2),
                ))
                avg_val = float(df["value"].mean())
                fig.add_hline(y=avg_val, line_dash="dash", line_color=C["amber"],
                              opacity=0.6, annotation_text="5yr avg",
                              annotation_font_color=C["amber"])
                latest = float(df2["value"].iloc[-1])
                diff = latest - avg_val
                sign = "+" if diff >= 0 else ""
                col = C["red"] if diff >= 0 else C["green"]
                fig.add_annotation(text=f"vs avg: {sign}{diff:,.0f}",
                    x=0.98, y=0.95, xref="paper", yref="paper",
                    showarrow=False, font=dict(color=col, size=11))
            fig.update_layout(
                title=dict(text=label, font=dict(size=12, color=C["text"]), x=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=8, r=8, t=32, b=8),
                xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=9)),
                yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"], tickfont=dict(size=9)),
                height=220,
            )
            return fig

        return html.Div([
            section_header("EIA Weekly Inventories", "US crude & products stocks — data from EIA.gov"),
            dbc.Row([
                dbc.Col(dcc.Graph(figure=inv_chart("crude",      "US Crude Stocks (k bbls)"),      config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=inv_chart("gasoline",   "US Gasoline Stocks (k bbls)"),   config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=inv_chart("distillate", "US Distillate Stocks (k bbls)"), config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=inv_chart("refutil",    "US Refinery Utilisation (%)"),   config={"displayModeBar": False}), md=6),
            ]),
        ])

    # ── COT POSITIONING ───────────────────────────────────────────────────────
    elif tab == "cot":
        cot = fetch_cot_data()
        df_cot = cot.get("df", pd.DataFrame())
        fig_net = go.Figure()
        if not df_cot.empty and "m_money_positions_long_all" in df_cot.columns:
            longs  = pd.to_numeric(df_cot["m_money_positions_long_all"],  errors="coerce")
            shorts = pd.to_numeric(df_cot["m_money_positions_short_all"], errors="coerce")
            net    = longs - shorts
            colors = [C["green"] if v >= 0 else C["red"] for v in net]
            fig_net.add_trace(go.Bar(x=df_cot["date"], y=net, marker_color=colors,
                hovertemplate="%{x|%b %d}: %{y:,.0f} contracts<extra></extra>"))
            latest_net = int(net.iloc[-1])
            net_pct = int((net.iloc[-1] - net.min()) / (net.max() - net.min()) * 100)
        else:
            latest_net, net_pct = 0, 50
            fig_net.add_annotation(text="Fetching CFTC data...", x=0.5, y=0.5,
                                   showarrow=False, font=dict(color=C["muted"]))
        fig_net.update_layout(
            title=dict(text="WTI Crude — Managed Money Net Position", font=dict(size=12, color=C["text"]), x=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=8, r=8, t=32, b=8),
            xaxis=dict(showgrid=False, color=C["muted"]),
            yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"]),
            height=280,
        )
        signal_col = C["red"] if net_pct > 75 else C["green"] if net_pct < 25 else C["amber"]
        signal_txt = ("⚠ Crowded long — reversal risk" if net_pct > 75
                      else "⚠ Crowded short — squeeze risk" if net_pct < 25
                      else "Positioning neutral")
        return html.Div([
            section_header("COT Positioning", "CFTC Commitment of Traders — managed money in WTI crude"),
            html.Div([
                html.Div(signal_txt, style={"fontSize": "14px", "fontWeight": "600", "color": signal_col}),
                html.Div(f"Net: {latest_net:+,} contracts  |  {net_pct}th percentile vs 1yr range",
                         style={"fontSize": "11px", "color": C["muted"], "marginTop": "4px"}),
            ], style={"background": C["card"], "border": f"1px solid {signal_col}44",
                      "borderLeft": f"3px solid {signal_col}", "borderRadius": "8px",
                      "padding": "14px 16px", "marginBottom": "16px"}),
            dcc.Graph(figure=fig_net, config={"displayModeBar": False}),
        ])

    # ── CRACK SPREADS ─────────────────────────────────────────────────────────
    elif tab == "cracks":
        def crack_chart(prod_sym, name, crude_sym="CL=F"):
            try:
                prod  = fetch_history(prod_sym,  period="1y")
                crude = fetch_history(crude_sym, period="1y")
                fig   = go.Figure()
                if prod.empty or crude.empty:
                    fig.add_annotation(text="Loading...", x=0.5, y=0.5,
                                       showarrow=False, font=dict(color=C["muted"]))
                else:
                    df = prod.join(crude, how="inner", lsuffix="_p", rsuffix="_c")
                    if prod_sym in ["RB=F", "HO=F"]:
                        df["crack"] = df["price_p"] * 42 - df["price_c"]
                    else:
                        df["crack"] = df["price_p"] - df["price_c"]
                    vals = df["crack"].values.flatten()
                    avg  = float(df["crack"].mean())
                    col  = C["green"] if float(vals[-1]) > avg else C["red"]
                    fig.add_trace(go.Scatter(x=df.index, y=vals, mode="lines",
                        line=dict(color=col, width=1.8), fill="tozeroy",
                        fillcolor=col+"18",
                        hovertemplate=f"{name}: %{{y:.2f}} $/bbl<extra></extra>"))
                    fig.add_hline(y=avg, line_dash="dash", line_color=C["amber"],
                                  opacity=0.5, annotation_text=f"1yr avg ${avg:.1f}",
                                  annotation_font_color=C["amber"], annotation_font_size=9)
                fig.update_layout(
                    title=dict(text=name, font=dict(size=12, color=C["text"]), x=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=8, r=8, t=32, b=8),
                    xaxis=dict(showgrid=False, color=C["muted"], tickfont=dict(size=9)),
                    yaxis=dict(showgrid=True, gridcolor=C["border"], color=C["muted"],
                               tickfont=dict(size=9), tickprefix="$"),
                    height=220,
                )
            except Exception:
                fig = go.Figure()
            return fig

        return html.Div([
            section_header("Crack Spreads", "Refinery margins — product vs crude, 1 year history"),
            dbc.Row([
                dbc.Col(dcc.Graph(figure=crack_chart("RB=F", "Gasoline Crack vs WTI $/bbl"),       config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=crack_chart("HO=F", "Diesel/Heat Crack vs WTI $/bbl"),    config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=crack_chart("RB=F", "Gasoline Crack vs Brent $/bbl", "BZ=F"), config={"displayModeBar": False}), md=6),
                dbc.Col(dcc.Graph(figure=crack_chart("HO=F", "Diesel Crack vs Brent $/bbl",  "BZ=F"), config={"displayModeBar": False}), md=6),
            ]),
        ])


# ── Run ───────────────────────────────────────────────────────────────────────
# ── Run ───────────────────────────────────────────────────────────────────────
import os
port = int(os.environ.get("PORT", 8050))

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=port)
