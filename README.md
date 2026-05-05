# Commodity Intelligence Dashboard

A real-time commodity & markets intelligence app built with Python + Dash.

## What it pulls in live
- **Commodity futures** — Brent, WTI, Henry Hub gas, gasoline, heating oil, gold, silver, copper, corn, wheat, soybeans, sugar, coffee, cotton (via yfinance / Yahoo Finance)
- **Energy equities** — XLE, XOP, ExxonMobil, Shell, BP, Total, Valero, Marathon
- **Freight proxies** — Euronav (VLCC), DHT, Frontline, Flex LNG, Golar LNG, BDRY (Baltic Dry ETF)
- **Macro** — DXY, VIX, US 10Y yield, EUR/USD, USD/CNY, USD/INR
- **Calculated spreads** — Brent-WTI, gasoline crack, heating oil crack, copper-gold ratio
- **Forward curves** — detects contango vs backwardation on Brent and WTI
- **News** — RSS feeds from Reuters, EIA, FT, Platts (best-effort; some feeds may require VPN)

## Setup

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python app.py
```

## Open in browser
```
http://localhost:8050
```

## Tabs
| Tab | What's there |
|-----|-------------|
| **Prices & Spreads** | Live metric cards for all instruments + key spread calculations + daily performance bar chart |
| **Charts** | 3-month price history for key commodities + forward curve (contango/backwardation) for Brent and WTI |
| **Freight & Flows** | Listed freight equity proxies + route explanations + shadow fleet context |
| **Market Structure** | Contango/backwardation, physical vs paper, COT report guide, crack spreads, freight as signal |
| **Participants** | Every major participant type in commodity and equity markets — who they are, what they trade, what they optimise for |
| **News** | Live RSS from Reuters, EIA, FT, Platts |

## Refresh
- Auto-refreshes every 5 minutes
- Manual refresh button top-right

## Upgrading data sources
For professional-grade data, replace yfinance calls with:
- **Argus / Platts API** — physical crude and products pricing
- **Kpler / Vortexa API** — real-time trade flow and AIS tracking
- **Baltic Exchange API** — official freight rates (TD3C, TD20, BCI etc.)
- **EIA API** (free, key required) — US inventory, production, refinery data
- **CFTC API** (free) — COT positioning data

## EIA free API (optional enhancement)
Sign up at https://www.eia.gov/opendata/
Add your key to a `.env` file:
```
EIA_API_KEY=your_key_here
```

## Notes
- Yahoo Finance (yfinance) is free but rate-limited. If you hit errors, wait 60 seconds and retry.
- Some RSS news feeds geo-restrict — use a VPN if FT/Platts feeds return empty.
- Forward curve data from Yahoo is approximate (front months only). For proper curves use CME/ICE data feeds.
