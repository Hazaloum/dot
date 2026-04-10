from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import glob
import math

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_GLOB = "budgetcars_*.xlsx"
AIRPORT_PATTERN = "Airport"
TARGET_DURATIONS = (1, 7, 30)
TARGET_LEAD_TIMES = (0, 7, 30)
CSV_LATEST_PATH = ROOT_DIR / "data" / "latest_market_prices.csv"
CSV_HISTORY_GLOB = str(ROOT_DIR / "data" / "history" / "market_prices_*.csv")


@dataclass(frozen=True)
class Scenario:
    lead_time_days: int
    duration_days: int

    @property
    def key(self) -> str:
        return f"lead_{self.lead_time_days}_duration_{self.duration_days}"

    @property
    def label(self) -> str:
        lead_label = {
            0: "Today",
            7: "+7 Days",
            30: "+30 Days",
        }.get(self.lead_time_days, f"+{self.lead_time_days} Days")
        duration_label = {
            1: "1 Day",
            7: "1 Week",
            30: "1 Month",
        }.get(self.duration_days, f"{self.duration_days} Days")
        return f"{duration_label} / {lead_label}"


SCENARIOS: tuple[Scenario, ...] = tuple(
    Scenario(lead_time_days=lead, duration_days=duration)
    for duration in TARGET_DURATIONS
    for lead in TARGET_LEAD_TIMES
)


def _normalize_supplier(supplier: object) -> str:
    return str(supplier).strip().lower()


def is_budget_supplier(supplier: object) -> bool:
    return "budget" in _normalize_supplier(supplier)


def _standardize_csv_quotes(df: pd.DataFrame) -> pd.DataFrame:
    standardized = df.copy()
    standardized["collection_date"] = pd.to_datetime(standardized.get("collection_date"), errors="coerce")
    standardized["pickup_date"] = pd.to_datetime(standardized.get("pickup_date"), errors="coerce")
    standardized["dropoff_date"] = pd.to_datetime(standardized.get("dropoff_date"), errors="coerce")
    standardized["duration_days"] = pd.to_numeric(standardized.get("duration_days"), errors="coerce")
    standardized["lead_time_days"] = pd.to_numeric(standardized.get("lead_time_days"), errors="coerce")
    standardized["price_per_day_aed"] = pd.to_numeric(standardized.get("price_per_day_aed"), errors="coerce")
    standardized["total_price_aed"] = pd.to_numeric(standardized.get("total_price_aed"), errors="coerce")
    standardized["supplier"] = standardized.get("supplier")
    standardized["car_name"] = standardized.get("car_name")
    standardized["pickup_location"] = standardized.get("pickup_location")
    standardized["source_file"] = standardized.get("source_file", "latest_market_prices.csv")
    standardized["sheet_name"] = standardized.get("scenario_key")
    standardized = standardized.dropna(
        subset=["collection_date", "pickup_date", "duration_days", "lead_time_days", "supplier", "car_name"]
    )
    standardized["duration_days"] = standardized["duration_days"].astype(int)
    standardized["lead_time_days"] = standardized["lead_time_days"].astype(int)
    standardized["collection_date_str"] = standardized["collection_date"].dt.strftime("%Y%m%d")
    standardized["pickup_date_str"] = standardized["pickup_date"].dt.strftime("%Y-%m-%d")
    standardized["is_airport"] = standardized["pickup_location"].fillna("").str.contains(AIRPORT_PATTERN, case=False)
    return standardized


def load_market_data_from_csv() -> tuple[pd.DataFrame, list[str]]:
    latest_path = CSV_LATEST_PATH
    if latest_path.exists():
        df = pd.read_csv(latest_path)
        return _standardize_csv_quotes(df), []
    return pd.DataFrame(), []


def load_market_history_from_csv() -> pd.DataFrame:
    history_files = sorted(Path(path) for path in glob.glob(CSV_HISTORY_GLOB))
    if not history_files:
        return pd.DataFrame()

    frames = [pd.read_csv(path) for path in history_files]
    combined = pd.concat(frames, ignore_index=True)
    return _standardize_csv_quotes(combined)


def find_data_files(base_dir: Path | None = None) -> list[Path]:
    search_dir = Path(base_dir) if base_dir else ROOT_DIR
    return sorted(Path(path) for path in glob.glob(str(search_dir / DATA_GLOB)))


def _extract_collection_date_from_filename(file_path: Path) -> str:
    return file_path.stem.replace("budgetcars_", "")


def _standardize_sheet(df: pd.DataFrame, collection_date: str, source_file: str, sheet_name: str) -> pd.DataFrame:
    standardized = pd.DataFrame(
        {
            "collection_date": pd.to_datetime(collection_date, format="%Y%m%d", errors="coerce"),
            "pickup_date": pd.to_datetime(df.get("Pickup Date"), errors="coerce"),
            "dropoff_date": pd.to_datetime(df.get("Dropoff Date"), errors="coerce"),
            "duration_days": pd.to_numeric(df.get("Interval Days"), errors="coerce"),
            "supplier": df.get("Supplier"),
            "car_name": df.get("Car Name"),
            "price_per_day_aed": pd.to_numeric(df.get("Price Per Day (AED)"), errors="coerce"),
            "total_price_aed": pd.to_numeric(df.get("Total Price (AED)"), errors="coerce"),
            "pickup_location": df.get("Pickup Location"),
            "source_file": source_file,
            "sheet_name": sheet_name,
        }
    )
    standardized["lead_time_days"] = (
        standardized["pickup_date"] - standardized["collection_date"]
    ).dt.days
    standardized["scenario_key"] = standardized.apply(
        lambda row: build_scenario_key(row["lead_time_days"], row["duration_days"]),
        axis=1,
    )
    return standardized


def load_market_data(base_dir: Path | None = None) -> tuple[pd.DataFrame, list[str]]:
    csv_data, csv_warnings = load_market_data_from_csv()
    if not csv_data.empty:
        return csv_data, csv_warnings

    files = find_data_files(base_dir)
    all_rows: list[pd.DataFrame] = []
    corrupted_files: list[str] = []

    for file_path in files:
        collection_date = _extract_collection_date_from_filename(file_path)
        try:
            excel_file = pd.ExcelFile(file_path)
        except Exception as exc:  # pragma: no cover
            corrupted_files.append(f"{file_path.name}: {exc}")
            continue

        for sheet_name in excel_file.sheet_names:
            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                standardized = _standardize_sheet(
                    df=df,
                    collection_date=collection_date,
                    source_file=file_path.name,
                    sheet_name=sheet_name,
                )
                all_rows.append(standardized)
            except Exception as exc:  # pragma: no cover
                corrupted_files.append(f"{file_path.name} [{sheet_name}]: {exc}")

    if not all_rows:
        return pd.DataFrame(), corrupted_files

    combined = pd.concat(all_rows, ignore_index=True)
    combined = combined.dropna(subset=["collection_date", "pickup_date", "duration_days", "car_name", "supplier"])
    combined["duration_days"] = combined["duration_days"].astype(int)
    combined["lead_time_days"] = combined["lead_time_days"].astype(int)
    combined["collection_date_str"] = combined["collection_date"].dt.strftime("%Y%m%d")
    combined["pickup_date_str"] = combined["pickup_date"].dt.strftime("%Y-%m-%d")
    combined["is_airport"] = combined["pickup_location"].fillna("").str.contains(AIRPORT_PATTERN, case=False)
    return combined, corrupted_files


def build_scenario_key(lead_time_days: int | float | None, duration_days: int | float | None) -> str | None:
    if lead_time_days is None or duration_days is None:
        return None
    if pd.isna(lead_time_days) or pd.isna(duration_days):
        return None
    lead = int(lead_time_days)
    duration = int(duration_days)
    return f"lead_{lead}_duration_{duration}"


def get_target_scenarios() -> tuple[Scenario, ...]:
    return SCENARIOS


def filter_target_market_rows(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data.copy()

    filtered = data.copy()
    filtered = filtered[filtered["is_airport"]]
    filtered = filtered[filtered["duration_days"].isin(TARGET_DURATIONS)]
    filtered = filtered[filtered["lead_time_days"].isin(TARGET_LEAD_TIMES)]
    filtered = filtered[filtered["scenario_key"].isin({scenario.key for scenario in SCENARIOS})]
    return filtered


def get_available_collection_dates(data: pd.DataFrame) -> list[str]:
    if data.empty:
        return []
    return sorted(data["collection_date_str"].dropna().unique().tolist())


def get_available_cars(data: pd.DataFrame, collection_date_str: str) -> list[str]:
    scoped = data[data["collection_date_str"] == collection_date_str]
    if scoped.empty:
        return []
    cars = scoped["car_name"].dropna().astype(str).str.strip()
    return sorted(car for car in cars.unique().tolist() if car)


def _format_rank(rank: int | None, total: int) -> str | None:
    if rank is None or total <= 0:
        return None
    return f"{rank}/{total}"


def _rounded(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), 2)


def summarize_scenario(
    data: pd.DataFrame,
    collection_date_str: str,
    car_name: str,
    scenario: Scenario,
    margin_pct: float,
) -> dict:
    scenario_rows = data[
        (data["collection_date_str"] == collection_date_str)
        & (data["car_name"] == car_name)
        & (data["scenario_key"] == scenario.key)
    ].copy()

    if scenario_rows.empty:
        return {
            "scenario_key": scenario.key,
            "scenario_label": scenario.label,
            "lead_time_days": scenario.lead_time_days,
            "duration_days": scenario.duration_days,
            "status": "insufficient_data",
            "budget_price_per_day": None,
            "competitor_floor_per_day": None,
            "competitor_median_per_day": None,
            "competitor_count": 0,
            "budget_rank": None,
            "recommended_price_per_day": None,
            "recommendation_reason": "No exact-match market rows found for this scenario.",
            "pickup_date": None,
        }

    budget_rows = scenario_rows[scenario_rows["supplier"].apply(is_budget_supplier)]
    competitor_rows = scenario_rows[~scenario_rows["supplier"].apply(is_budget_supplier)]
    pickup_date = scenario_rows["pickup_date_str"].dropna().min()

    budget_price = _rounded(budget_rows["price_per_day_aed"].min()) if not budget_rows.empty else None
    competitor_floor = _rounded(competitor_rows["price_per_day_aed"].min()) if not competitor_rows.empty else None
    competitor_median = _rounded(competitor_rows["price_per_day_aed"].median()) if not competitor_rows.empty else None
    competitor_count = int(competitor_rows["supplier"].nunique())

    budget_rank = None
    total_market_rows = scenario_rows["price_per_day_aed"].dropna()
    if budget_price is not None and not total_market_rows.empty:
        budget_rank = int((total_market_rows < budget_price).sum() + 1)

    if budget_rows.empty:
        status = "no_budget_offer"
        recommended_price = _rounded(competitor_floor * (1 + margin_pct)) if competitor_floor is not None else None
        reason = "Budget is not present in this exact-match market snapshot."
    elif competitor_rows.empty:
        status = "no_competitors"
        recommended_price = None
        reason = "Budget is the only exact-match offer, so no competitor-based recommendation is available."
    else:
        status = "ok"
        recommended_price = _rounded(competitor_floor * (1 + margin_pct))
        rank_label = _format_rank(budget_rank, len(total_market_rows))
        reason = (
            f"Recommend AED {recommended_price:.2f}/day: competitor floor AED {competitor_floor:.2f} "
            f"+ {margin_pct:.0%} margin. Current Budget rank: {rank_label}."
        )

    return {
        "scenario_key": scenario.key,
        "scenario_label": scenario.label,
        "lead_time_days": scenario.lead_time_days,
        "duration_days": scenario.duration_days,
        "status": status,
        "budget_price_per_day": budget_price,
        "competitor_floor_per_day": competitor_floor,
        "competitor_median_per_day": competitor_median,
        "competitor_count": competitor_count,
        "budget_rank": _format_rank(budget_rank, len(total_market_rows)),
        "recommended_price_per_day": recommended_price,
        "recommendation_reason": reason,
        "pickup_date": pickup_date,
    }


def build_pricing_matrix(
    data: pd.DataFrame,
    collection_date_str: str,
    car_name: str,
    margin_pct: float,
) -> pd.DataFrame:
    rows = [
        summarize_scenario(
            data=data,
            collection_date_str=collection_date_str,
            car_name=car_name,
            scenario=scenario,
            margin_pct=margin_pct,
        )
        for scenario in SCENARIOS
    ]
    return pd.DataFrame(rows)


def get_market_rows_for_scenario(
    data: pd.DataFrame,
    collection_date_str: str,
    car_name: str,
    scenario_key: str,
) -> pd.DataFrame:
    scoped = data[
        (data["collection_date_str"] == collection_date_str)
        & (data["car_name"] == car_name)
        & (data["scenario_key"] == scenario_key)
    ].copy()
    if scoped.empty:
        return scoped

    scoped["market_role"] = scoped["supplier"].apply(
        lambda supplier: "Budget" if is_budget_supplier(supplier) else "Competitor"
    )
    scoped = scoped.sort_values(["price_per_day_aed", "supplier"], na_position="last")
    return scoped[
        [
            "market_role",
            "supplier",
            "car_name",
            "pickup_date_str",
            "duration_days",
            "lead_time_days",
            "price_per_day_aed",
            "total_price_aed",
            "pickup_location",
            "source_file",
            "sheet_name",
        ]
    ]


def compute_collection_coverage(data: pd.DataFrame, collection_date_str: str) -> dict[str, int]:
    scoped = data[data["collection_date_str"] == collection_date_str]
    scenario_count = int(scoped["scenario_key"].nunique()) if not scoped.empty else 0
    car_count = int(scoped["car_name"].nunique()) if not scoped.empty else 0
    row_count = int(len(scoped))
    return {
        "scenario_count": scenario_count,
        "car_count": car_count,
        "row_count": row_count,
    }
