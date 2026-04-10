from __future__ import annotations

import argparse
import http.client
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


API_HOST = "booking-com18.p.rapidapi.com"
DEFAULT_AIRPORT_ID = "eyJsYXRpdHVkZSI6IjI1LjI1IiwibG9uZ2l0dWRlIjoiNTUuMzU2OTk4NDQzNjAzNSJ9"
DEFAULT_PICKUP_TIME = "10:00"
DEFAULT_DROPOFF_TIME = "10:00"
DEFAULT_PAGES = 1
DEFAULT_USD_TO_AED = 3.68
TARGET_DURATIONS = (1, 7, 30)
TARGET_LEAD_TIMES = (0, 7, 30)
OUTPUT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = OUTPUT_ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
LATEST_CSV = DATA_DIR / "latest_market_prices.csv"


@dataclass(frozen=True)
class Scenario:
    lead_time_days: int
    duration_days: int

    @property
    def key(self) -> str:
        return f"lead_{self.lead_time_days}_duration_{self.duration_days}"


def build_scenarios() -> list[Scenario]:
    return [
        Scenario(lead_time_days=lead, duration_days=duration)
        for duration in TARGET_DURATIONS
        for lead in TARGET_LEAD_TIMES
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Booking.com pricing for the Budget 3x3 scenario matrix.")
    parser.add_argument("--output-dir", default=str(OUTPUT_ROOT), help="Directory where CSV and optional XLSX files will be written.")
    parser.add_argument("--skip-xlsx", action="store_true", help="Do not write the legacy XLSX workbook.")
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES, help="How many result pages to fetch per scenario.")
    parser.add_argument("--pickup-time", default=DEFAULT_PICKUP_TIME, help="Pickup time in HH:MM.")
    parser.add_argument("--dropoff-time", default=DEFAULT_DROPOFF_TIME, help="Dropoff time in HH:MM.")
    parser.add_argument("--airport-id", default=os.getenv("BOOKING_AIRPORT_ID") or DEFAULT_AIRPORT_ID, help="Encoded Booking.com pickup airport id.")
    parser.add_argument("--api-key", default=os.getenv("RAPIDAPI_KEY", ""), help="RapidAPI key. Defaults to RAPIDAPI_KEY env var.")
    parser.add_argument("--usd-to-aed", type=float, default=float(os.getenv("USD_TO_AED") or DEFAULT_USD_TO_AED), help="Conversion rate when API returns USD.")
    parser.add_argument("--date", default="", help="Collection anchor date in YYYY-MM-DD. Defaults to today.")
    return parser.parse_args()


def encode_time(value: str) -> str:
    return value.replace(":", "%3A")


def build_search_path(
    airport_id: str,
    pickup_date: str,
    dropoff_date: str,
    pickup_time: str,
    dropoff_time: str,
    page: int,
) -> str:
    base = (
        f"/car/search?pickUpId={airport_id}"
        f"&pickUpDate={pickup_date}"
        f"&pickUpTime={encode_time(pickup_time)}"
        f"&dropOffDate={dropoff_date}"
        f"&dropOffTime={encode_time(dropoff_time)}"
    )
    return base if page == 1 else f"{base}&page={page}"


def convert_price_to_aed(total_price: Any, currency: str | None, usd_to_aed: float) -> float | None:
    if total_price is None:
        return None
    try:
        numeric_price = float(total_price)
    except (TypeError, ValueError):
        return None

    normalized_currency = (currency or "").upper()
    if normalized_currency == "AED":
        return round(numeric_price, 2)
    if normalized_currency in {"USD", ""}:
        return round(numeric_price * usd_to_aed, 2)
    return round(numeric_price, 2)


def fetch_json(path: str, api_key: str) -> dict:
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": API_HOST,
    }
    conn = http.client.HTTPSConnection(API_HOST)
    conn.request("GET", path, headers=headers)
    response = conn.getresponse()
    payload = response.read()
    if response.status >= 400:
        raise RuntimeError(f"API error {response.status}: {payload[:500]!r}")
    return json.loads(payload.decode("utf-8"))


def extract_rows(
    response: dict,
    scenario: Scenario,
    pickup_date: str,
    dropoff_date: str,
    collection_date_str: str,
    pickup_time: str,
    dropoff_time: str,
    usd_to_aed: float,
) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(response, dict):
        return []
    search_results = response.get("data", {}).get("search_results", [])

    for car in search_results:
        vehicle_info = car.get("vehicle_info", {})
        content = car.get("content", {})
        supplier_info = content.get("supplier", {})
        route_info = car.get("route_info", {})
        pickup_info = route_info.get("pickup", {})
        dropoff_info = route_info.get("dropoff", {})
        pricing_info = car.get("pricing_info", {})
        rating_info = car.get("rating_info", {})

        vehicle_id = vehicle_info.get("v_id")
        supplier = supplier_info.get("name")
        pickup_location = pickup_info.get("name")
        unique_vehicle_key = f"{vehicle_id}_{supplier}_{pickup_location}"

        total_price_raw = pricing_info.get("price")
        currency = pricing_info.get("currency")
        total_price_aed = convert_price_to_aed(total_price_raw, currency, usd_to_aed)
        price_per_day_aed = (
            round(total_price_aed / scenario.duration_days, 2)
            if total_price_aed is not None and scenario.duration_days > 0
            else None
        )

        rows.append(
            {
                "unique_vehicle_key": unique_vehicle_key,
                "scenario_key": scenario.key,
                "lead_time_days": scenario.lead_time_days,
                "duration_days": scenario.duration_days,
                "collection_date": collection_date_str,
                "pickup_date": pickup_date,
                "dropoff_date": dropoff_date,
                "pickup_time": pickup_time,
                "dropoff_time": dropoff_time,
                "supplier": supplier,
                "car_name": str(vehicle_info.get("v_name", "")).strip(),
                "category": vehicle_info.get("group"),
                "pickup_location": pickup_location,
                "dropoff_location": dropoff_info.get("name"),
                "price_per_day_aed": price_per_day_aed,
                "total_price_aed": total_price_aed,
                "mileage": vehicle_info.get("mileage"),
                "source_currency": currency,
                "supplier_rating": rating_info.get("average"),
                "rating_text": rating_info.get("average_text"),
                "number_of_reviews": rating_info.get("no_of_ratings"),
                "condition_rating": rating_info.get("condition"),
                "location_rating": rating_info.get("location"),
                "cleanliness_rating": rating_info.get("cleanliness"),
                "efficiency_rating": rating_info.get("efficiency"),
                "value_for_money_rating": rating_info.get("value_for_money"),
                "pickup_time_rating": rating_info.get("pickup_time"),
                "dropoff_time_rating": rating_info.get("dropoff_time"),
            }
        )

    return rows


def fetch_scenario_rows(
    scenario: Scenario,
    collection_date: datetime,
    api_key: str,
    airport_id: str,
    pickup_time: str,
    dropoff_time: str,
    pages: int,
    usd_to_aed: float,
) -> pd.DataFrame:
    pickup_date = (collection_date + timedelta(days=scenario.lead_time_days)).strftime("%Y-%m-%d")
    dropoff_date = (collection_date + timedelta(days=scenario.lead_time_days + scenario.duration_days)).strftime("%Y-%m-%d")
    collection_date_str = collection_date.strftime("%Y-%m-%d")

    deduped_rows: dict[str, dict] = {}

    for page in range(1, pages + 1):
        path = build_search_path(
            airport_id=airport_id,
            pickup_date=pickup_date,
            dropoff_date=dropoff_date,
            pickup_time=pickup_time,
            dropoff_time=dropoff_time,
            page=page,
        )
        response = fetch_json(path, api_key)
        for row in extract_rows(
            response=response,
            scenario=scenario,
            pickup_date=pickup_date,
            dropoff_date=dropoff_date,
            collection_date_str=collection_date_str,
            pickup_time=pickup_time,
            dropoff_time=dropoff_time,
            usd_to_aed=usd_to_aed,
        ):
            deduped_rows[row["unique_vehicle_key"]] = row

    return pd.DataFrame(deduped_rows.values())


def build_legacy_sheet(df: pd.DataFrame, scenario: Scenario, pickup_time: str, dropoff_time: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Unique ID",
                "Supplier",
                "Car Name",
                "Category",
                "Pickup Location",
                "Dropoff Location",
                "Pickup Date",
                "Pickup Time",
                "Dropoff Date",
                "Dropoff Time",
                "Interval Days",
                "Total Price (AED)",
                "Price Per Day (AED)",
                "Mileage",
                "Collection Date",
                "Supplier Rating",
                "Rating Text",
                "Number of Reviews",
                "Condition Rating",
                "Location Rating",
                "Cleanliness Rating",
                "Efficiency Rating",
                "Value for Money Rating",
                "Pickup Time Rating",
                "Dropoff Time Rating",
            ]
        )

    return pd.DataFrame(
        {
            "Unique ID": df["unique_vehicle_key"],
            "Supplier": df["supplier"],
            "Car Name": df["car_name"],
            "Category": df["category"],
            "Pickup Location": df["pickup_location"],
            "Dropoff Location": df["dropoff_location"],
            "Pickup Date": df["pickup_date"],
            "Pickup Time": pickup_time,
            "Dropoff Date": df["dropoff_date"],
            "Dropoff Time": dropoff_time,
            "Interval Days": scenario.duration_days,
            "Total Price (AED)": df["total_price_aed"],
            "Price Per Day (AED)": df["price_per_day_aed"],
            "Mileage": df["mileage"],
            "Collection Date": df["collection_date"],
            "Supplier Rating": df["supplier_rating"],
            "Rating Text": df["rating_text"],
            "Number of Reviews": df["number_of_reviews"],
            "Condition Rating": df["condition_rating"],
            "Location Rating": df["location_rating"],
            "Cleanliness Rating": df["cleanliness_rating"],
            "Efficiency Rating": df["efficiency_rating"],
            "Value for Money Rating": df["value_for_money_rating"],
            "Pickup Time Rating": df["pickup_time_rating"],
            "Dropoff Time Rating": df["dropoff_time_rating"],
        }
    )


def write_workbook(output_dir: Path, collection_date: datetime, sheets: dict[str, pd.DataFrame]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"budgetcars_{collection_date.strftime('%Y%m%d')}.xlsx"
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return filename


def write_csv_snapshots(output_dir: Path, collection_date: datetime, quotes_df: pd.DataFrame) -> tuple[Path, Path]:
    data_dir = output_dir / DATA_DIR.name
    history_dir = data_dir / HISTORY_DIR.name
    data_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    latest_path = data_dir / LATEST_CSV.name
    history_path = history_dir / f"market_prices_{collection_date.strftime('%Y%m%d')}.csv"

    quotes_df.to_csv(latest_path, index=False)
    quotes_df.to_csv(history_path, index=False)
    return latest_path, history_path


def main() -> int:
    args = parse_args()
    if not args.api_key:
        raise SystemExit("Missing RapidAPI key. Set RAPIDAPI_KEY or pass --api-key.")

    collection_date = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.now()
    scenarios = build_scenarios()
    sheets: dict[str, pd.DataFrame] = {}
    quote_frames: list[pd.DataFrame] = []

    print("=" * 80)
    print("BOOKING.COM 3x3 PRICING COLLECTION")
    print("=" * 80)
    print(f"Collection date: {collection_date.strftime('%Y-%m-%d')}")
    print(f"Airport id: {args.airport_id}")
    print(f"Pages per scenario: {args.pages}")
    print("=" * 80)

    for scenario in scenarios:
        print(
            f"Fetching {scenario.key}: lead={scenario.lead_time_days} days, duration={scenario.duration_days} days"
        )
        normalized_df = fetch_scenario_rows(
            scenario=scenario,
            collection_date=collection_date,
            api_key=args.api_key,
            airport_id=args.airport_id,
            pickup_time=args.pickup_time,
            dropoff_time=args.dropoff_time,
            pages=args.pages,
            usd_to_aed=args.usd_to_aed,
        )
        if not normalized_df.empty:
            quote_frames.append(normalized_df)
        sheets[f"{scenario.key}_{collection_date.strftime('%Y%m%d')}"] = build_legacy_sheet(
            normalized_df,
            scenario=scenario,
            pickup_time=args.pickup_time,
            dropoff_time=args.dropoff_time,
        )
        print(f"  -> {len(normalized_df)} unique rows")

    combined_quotes = pd.concat(quote_frames, ignore_index=True) if quote_frames else pd.DataFrame()
    latest_path, history_path = write_csv_snapshots(Path(args.output_dir), collection_date, combined_quotes)

    print("=" * 80)
    print(f"Saved latest CSV: {latest_path}")
    print(f"Saved history CSV: {history_path}")

    if not args.skip_xlsx:
        output_file = write_workbook(Path(args.output_dir), collection_date, sheets)
        print(f"Saved workbook: {output_file}")
    else:
        print("Skipped XLSX export")

    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
