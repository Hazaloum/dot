# CLAUDE.md

## Project purpose

This folder contains the active Streamlit pricing benchmark tool for Budget Rent A Car in Dubai.

The current product goal is narrow and operational:
- choose an exact car model
- choose one booking scenario
- compare Budget's displayed Booking.com price against the market
- visualize competitor prices clearly
- optionally use a deterministic recommendation based on market floor plus a configurable margin

This folder is the source of truth for the current product. Legacy notebooks and dashboards in the repo root are reference material only.

## Active file structure

Inside `AI Pricing department Budget/`:

- `Dashboard.py`
  Streamlit UI entrypoint. Handles login gate, selectors, chart rendering, and top-level product flow.
- `pricing_engine.py`
  Core data loading, scenario normalization, filtering, and recommendation logic.
- `collect_booking_api_data.py`
  Booking.com market collector using RapidAPI. Writes CSV snapshots plus optional legacy XLSX exports.
- `requirements.txt`
  Minimal runtime dependencies for deployment.
- `README.md`
  Run instructions, collector instructions, and password secret names.
- `tests/test_pricing_engine.py`
  Basic unit tests for scenario keys and recommendation logic.

## Product model

The current product model is:

- unit of analysis: exact `Car Name`
- comparison basis: `Price Per Day (AED)`
- source of "our" price: the `Budget` row returned by the Booking.com market scrape
- comparison set: same exact `Car Name` in the same scenario
- fallback policy: no category fallback in v1

The user experience is intentionally simple:

1. Select collection date
2. Select car model
3. Select rental duration
4. Select lead time
5. View one benchmark chart with Budget highlighted

## Scenario model

The app is built around a fixed `3 x 3` scenario grid:

- rental durations:
  - `1`
  - `7`
  - `30`
- lead times:
  - `0`
  - `7`
  - `30`

Scenario key format:

- `lead_0_duration_1`
- `lead_7_duration_7`
- `lead_30_duration_30`

Important nuance:
- same-day (`lead_0`) airport availability can be empty if the collector uses a pickup time earlier than the current time
- this is a known product/data issue and likely should be changed later to `next valid pickup time` or `tomorrow`

## Data flow

### 1. Collection

`collect_booking_api_data.py`:

- calls `booking-com18.p.rapidapi.com`
- uses the DXB airport `pickUpId`
- requests the 9 fixed scenarios
- extracts supplier, car, pricing, location, dates, and rating data
- converts price to AED
- deduplicates by:
  - vehicle id
  - supplier
  - pickup location
- writes a workbook:
  - `budgetcars_YYYYMMDD.xlsx`

Each sheet is named like:
- `lead_7_duration_1_20260329`

The collector writes to the repo root, not the app subfolder.

### 2. Persist

`collect_booking_api_data.py` writes:

- `data/latest_market_prices.csv`
  canonical current snapshot used by the app
- `data/history/market_prices_YYYYMMDD.csv`
  daily archive for historical/trend work later
- optional `budgetcars_YYYYMMDD.xlsx`
  legacy/local fallback export

### 3. Load + standardize

`pricing_engine.load_market_data()`:

- reads `data/latest_market_prices.csv` first
- otherwise falls back to local `budgetcars_*.xlsx` files in the repo root
- standardizes fields into a common schema:
  - `collection_date`
  - `pickup_date`
  - `dropoff_date`
  - `duration_days`
  - `lead_time_days`
  - `supplier`
  - `car_name`
  - `price_per_day_aed`
  - `total_price_aed`
  - `pickup_location`
  - `scenario_key`

### 4. Filter

`pricing_engine.filter_target_market_rows()`:

- keeps airport rows only
- keeps only durations `1`, `7`, `30`
- keeps only lead times `0`, `7`, `30`
- keeps only valid scenario keys in the fixed matrix

### 5. Recommendation

`pricing_engine.summarize_scenario()`:

- isolates one exact car + one scenario + one collection date
- identifies Budget rows
- identifies non-Budget competitor rows
- computes:
  - Budget price
  - competitor floor
  - competitor median
  - competitor count
  - Budget rank
- recommends:
  - `competitor_floor * (1 + margin_pct)`

Statuses:
- `ok`
- `insufficient_data`
- `no_budget_offer`
- `no_competitors`

### 6. Presentation

`Dashboard.py`:

- optionally gates access using Streamlit secrets
- loads filtered data
- lets the user select:
  - collection date
  - car
  - rental length
  - booking timing
  - margin percentage
- renders:
  - current date label
  - summary metrics
  - one supplier bar chart
  - Budget reference line
  - percentage labels versus Budget
  - optional raw market rows in an expander

## Authentication model

The app supports lightweight shared login through Streamlit secrets.

Expected secrets:

- `APP_USERNAME`
- `APP_PASSWORD`

Behavior:
- if `APP_PASSWORD` is not set, the app is open
- if `APP_PASSWORD` is set, the app requires login

The login logic is implemented directly in `Dashboard.py` via `check_password()`.

## Deployment assumptions

This folder is suitable for a simple Streamlit deployment.

Likely deployment model:
- deploy `Dashboard.py`
- install `requirements.txt`
- set Streamlit secrets for:
  - `APP_USERNAME`
  - `APP_PASSWORD`
- set GitHub Actions secrets for:
  - `RAPIDAPI_KEY`
  - optional `BOOKING_AIRPORT_ID`
  - optional `USD_TO_AED`

Important:
- generated `budgetcars_*.xlsx` files are ignored by git via the repo `.gitignore`
- production should use the CSV-backed path under `data/`
- a GitHub Actions workflow is the intended daily scheduler later

## Known limitations

1. Same-day scenarios can legitimately return empty data
   This is caused by pickup-time semantics, not necessarily a bug in parsing.

2. Exact `Car Name` matching is brittle
   If Booking changes naming slightly, matches may fragment across suppliers.

3. No category fallback exists
   This is intentional in v1, but it limits coverage for sparse exact-match scenarios.

4. Historical workbooks use different shapes
   The engine tolerates this as long as the normalized fields can be derived.

5. Tests exist but are lightweight
   More coverage is needed around collector parsing, chart assumptions, and date semantics.

## How to work on this codebase

If you are a new agent entering this repository:

1. Start in this folder: `AI Pricing department Budget/`
2. Treat `Dashboard.py` as the product surface
3. Treat `pricing_engine.py` as the source of truth for data normalization and recommendation logic
4. Treat `collect_booking_api_data.py` as the source of truth for live Booking.com collection
5. Ignore legacy dashboards unless the task explicitly references them

Typical tasks map as follows:

- UI / product changes:
  - `Dashboard.py`
- recommendation / logic changes:
  - `pricing_engine.py`
- collection / scenario generation changes:
  - `collect_booking_api_data.py`
- CSV storage / history changes:
  - `collect_booking_api_data.py`
  - `pricing_engine.py`
- deployment / dependency changes:
  - `requirements.txt`
  - `README.md`

## Common commands

Run the app:

```bash
cd "/Users/yahyakhaled/Desktop/Batha Work/Budget BookingAPI/AI Pricing department Budget"
/opt/anaconda3/bin/streamlit run Dashboard.py
```

Collect live data:

```bash
cd "/Users/yahyakhaled/Desktop/Batha Work/Budget BookingAPI/AI Pricing department Budget"
export RAPIDAPI_KEY="your-key"
/opt/anaconda3/bin/python collect_booking_api_data.py --skip-xlsx
```

Compile-check Python files:

```bash
python3 -m py_compile Dashboard.py pricing_engine.py collect_booking_api_data.py
```

## Recommended next improvements

Good next product steps:

- convert `lead_0` to `tomorrow` or `next valid pickup time`
- add a `Lower / Hold / Raise` action indicator
- overlay recommended price directly on the chart
- add a compact 3x3 overview for the selected car
- improve action cues on the UI
- use `data/history/` to build trend views
