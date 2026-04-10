# Budget AI Pricing Department

Standalone v1 pricing app for Budget based on a fixed daily 3 x 3 scenario matrix.

## What it does

- Reads `data/latest_market_prices.csv` as the primary live snapshot
- Keeps archived daily snapshots in `data/history/`
- Falls back to `budgetcars_*.xlsx` workbooks in the repo root when no CSV snapshot exists
- Standardizes each row into a pricing snapshot
- Filters to airport rows only
- Evaluates exact car-name matches for:
  - `1 day`, `7 days`, `30 days` rentals
  - booked `today`, `+7 days`, `+30 days`
- Recommends a price using `competitor floor * (1 + margin)`

## Booking API collection

The existing repo already contains Booking.com collection logic in [BookingAPI.ipynb](/Users/yahyakhaled/Desktop/Batha%20Work/Budget%20BookingAPI/BookingAPI.ipynb). This folder now also includes a reusable collector script:

```bash
cd "/Users/yahyakhaled/Desktop/Batha Work/Budget BookingAPI/AI Pricing department Budget"
export RAPIDAPI_KEY="your-key"
python3 collect_booking_api_data.py
```

That script:
- calls `booking-com18.p.rapidapi.com`
- fetches the fixed 9 scenarios
- deduplicates rows by vehicle + supplier + pickup location
- writes `data/latest_market_prices.csv`
- archives `data/history/market_prices_YYYYMMDD.csv`
- optionally writes `budgetcars_YYYYMMDD.xlsx` to the repo root for local fallback/debugging

Optional flags:

```bash
python3 collect_booking_api_data.py --date 2026-03-29 --pages 1
python3 collect_booking_api_data.py --skip-xlsx
```

The collector defaults to a single request per scenario, matching your current DXB workflow. If Booking starts paging airport results again, increase `--pages`.

## CSV-backed deployment

Recommended production setup:

- app host: Streamlit Community Cloud
- storage: versioned CSV files in the repo
- scheduler: GitHub Actions

Required secrets for production:

```toml
APP_USERNAME = "team"
APP_PASSWORD = "your-shared-password"
RAPIDAPI_KEY = "your-rapidapi-key"
BOOKING_AIRPORT_ID = "optional-override"
USD_TO_AED = "3.68"
```

Behavior:

- the app reads `data/latest_market_prices.csv`
- history lives in `data/history/`
- the GitHub Actions workflow at `.github/workflows/daily_pricing_collection.yml` runs the collector every day at `04:00 UTC` which is `08:00` in Dubai

## Password protection

The dashboard supports a shared login if you set these Streamlit secrets:

```toml
APP_USERNAME = "team"
APP_PASSWORD = "your-shared-password"
```

If `APP_PASSWORD` is not set, the app stays open without login.

## Run

```bash
cd "/Users/yahyakhaled/Desktop/Batha Work/Budget BookingAPI/AI Pricing department Budget"
streamlit run Dashboard.py
```

## Test

```bash
cd "/Users/yahyakhaled/Desktop/Batha Work/Budget BookingAPI/AI Pricing department Budget"
python3 -m pytest tests/test_pricing_engine.py
```
