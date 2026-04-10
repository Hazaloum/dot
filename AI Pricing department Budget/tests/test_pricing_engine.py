from pathlib import Path
import sys

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pricing_engine import (  # noqa: E402
    Scenario,
    build_pricing_matrix,
    build_scenario_key,
    summarize_scenario,
)


def sample_market_data() -> pd.DataFrame:
    rows = [
        {
            "collection_date_str": "20260329",
            "pickup_date_str": "2026-03-29",
            "scenario_key": "lead_0_duration_1",
            "lead_time_days": 0,
            "duration_days": 1,
            "supplier": "Budget",
            "car_name": "Toyota Yaris",
            "price_per_day_aed": 120.0,
            "total_price_aed": 120.0,
            "pickup_location": "Dubai International Airport",
        },
        {
            "collection_date_str": "20260329",
            "pickup_date_str": "2026-03-29",
            "scenario_key": "lead_0_duration_1",
            "lead_time_days": 0,
            "duration_days": 1,
            "supplier": "Avis",
            "car_name": "Toyota Yaris",
            "price_per_day_aed": 100.0,
            "total_price_aed": 100.0,
            "pickup_location": "Dubai International Airport",
        },
        {
            "collection_date_str": "20260329",
            "pickup_date_str": "2026-03-29",
            "scenario_key": "lead_0_duration_1",
            "lead_time_days": 0,
            "duration_days": 1,
            "supplier": "Hertz",
            "car_name": "Toyota Yaris",
            "price_per_day_aed": 140.0,
            "total_price_aed": 140.0,
            "pickup_location": "Dubai International Airport",
        },
        {
            "collection_date_str": "20260329",
            "pickup_date_str": "2026-04-05",
            "scenario_key": "lead_7_duration_7",
            "lead_time_days": 7,
            "duration_days": 7,
            "supplier": "Avis",
            "car_name": "Toyota Yaris",
            "price_per_day_aed": 90.0,
            "total_price_aed": 630.0,
            "pickup_location": "Dubai International Airport",
        },
    ]
    return pd.DataFrame(rows)


def test_build_scenario_key():
    assert build_scenario_key(7, 30) == "lead_7_duration_30"


def test_summarize_scenario_ok():
    data = sample_market_data()
    scenario = Scenario(lead_time_days=0, duration_days=1)

    result = summarize_scenario(data, "20260329", "Toyota Yaris", scenario, 0.15)

    assert result["status"] == "ok"
    assert result["competitor_floor_per_day"] == 100.0
    assert result["competitor_median_per_day"] == 120.0
    assert result["budget_rank"] == "2/3"
    assert result["recommended_price_per_day"] == 115.0


def test_summarize_scenario_without_budget():
    data = sample_market_data()
    scenario = Scenario(lead_time_days=7, duration_days=7)

    result = summarize_scenario(data, "20260329", "Toyota Yaris", scenario, 0.10)

    assert result["status"] == "no_budget_offer"
    assert result["recommended_price_per_day"] == 99.0


def test_build_pricing_matrix_has_all_nine_scenarios():
    data = sample_market_data()

    matrix = build_pricing_matrix(data, "20260329", "Toyota Yaris", 0.15)

    assert len(matrix) == 9
    assert set(matrix["scenario_key"]) == {
        "lead_0_duration_1",
        "lead_7_duration_1",
        "lead_30_duration_1",
        "lead_0_duration_7",
        "lead_7_duration_7",
        "lead_30_duration_7",
        "lead_0_duration_30",
        "lead_7_duration_30",
        "lead_30_duration_30",
    }

