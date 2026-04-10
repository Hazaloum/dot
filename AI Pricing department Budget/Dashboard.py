from __future__ import annotations

import hmac
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pricing_engine import (
    ROOT_DIR,
    build_pricing_matrix,
    filter_target_market_rows,
    get_available_cars,
    get_available_collection_dates,
    get_market_rows_for_scenario,
    load_market_data,
)


SCENARIO_LABELS = {
    (1, 0): "1 Day / Today",
    (1, 7): "1 Day / +7 Days",
    (1, 30): "1 Day / +30 Days",
    (7, 0): "1 Week / Today",
    (7, 7): "1 Week / +7 Days",
    (7, 30): "1 Week / +30 Days",
    (30, 0): "1 Month / Today",
    (30, 7): "1 Month / +7 Days",
    (30, 30): "1 Month / +30 Days",
}


st.set_page_config(
    page_title="Budget AI Pricing Department",
    layout="wide",
    page_icon="💰",
)

st.title("Budget AI Pricing Department")
st.markdown("Select a car and one booking scenario, then benchmark Budget against the market.")


@st.cache_data(show_spinner=False)
def load_dashboard_data() -> tuple[pd.DataFrame, list[str]]:
    raw_data, corrupted_files = load_market_data(ROOT_DIR)
    return filter_target_market_rows(raw_data), corrupted_files


def normalize_car_name(name):
    if pd.isna(name):
        return None
    normalized = str(name).lower().strip()
    normalized = " ".join(normalized.split())
    normalized = normalized.replace("-", " ").replace("_", " ")
    return normalized


@st.cache_data(show_spinner=False)
def load_acriss_mapping() -> tuple[dict[str, str], dict[str, list[str]]]:
    try:
        df = pd.read_excel(ROOT_DIR / "Rate.xlsx", sheet_name="Data 2")
        mapping = df[["car_model", "car_group"]].drop_duplicates()
        mapping = mapping[mapping["car_model"].notna() & mapping["car_group"].notna()]
        mapping["car_model_normalized"] = mapping["car_model"].apply(normalize_car_name)

        car_to_acriss: dict[str, str] = {}
        acriss_to_cars: dict[str, set[str]] = {}

        for _, row in mapping.iterrows():
            normalized = row["car_model_normalized"]
            acriss = str(row["car_group"]).strip()
            original_name = str(row["car_model"]).strip()
            if normalized and normalized not in car_to_acriss:
                car_to_acriss[normalized] = acriss
            if normalized:
                acriss_to_cars.setdefault(acriss, set()).add(original_name)

        return car_to_acriss, {key: sorted(list(value)) for key, value in acriss_to_cars.items()}
    except Exception:
        return {}, {}


def format_currency(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"AED {round(float(value)):,.0f}"


def format_long_date(value: str) -> str:
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        return value
    day = parsed.day
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} of {parsed.strftime('%B, %Y')}"


def format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.1f}%"


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = default
    return str(value).strip()


def check_password() -> bool:
    expected_password = get_secret("APP_PASSWORD")
    expected_username = get_secret("APP_USERNAME", "team")

    if not expected_password:
        return True

    if st.session_state.get("authenticated", False):
        return True

    with st.form("login_form"):
        st.subheader("Team Access")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        username_ok = hmac.compare_digest(username.strip(), expected_username)
        password_ok = hmac.compare_digest(password, expected_password)
        if username_ok and password_ok:
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Invalid username or password.")

    st.stop()


def attach_acriss_codes(data: pd.DataFrame, car_to_acriss: dict[str, str]) -> pd.DataFrame:
    enriched = data.copy()
    enriched["car_name_normalized"] = enriched["car_name"].apply(normalize_car_name)
    enriched["acriss_code"] = enriched["car_name_normalized"].map(car_to_acriss)
    return enriched


def summarize_market_rows(market_rows: pd.DataFrame, margin_pct: float) -> dict[str, object]:
    if market_rows.empty:
        return {
            "budget_price": None,
            "competitor_floor": None,
            "competitor_median": None,
            "recommended_price": None,
            "budget_rank": "-",
        }

    budget_rows = market_rows[market_rows["Role"] == "Budget"]
    competitor_rows = market_rows[market_rows["Role"] != "Budget"]

    budget_price = budget_rows["Price / Day (AED)"].min() if not budget_rows.empty else None
    competitor_floor = competitor_rows["Price / Day (AED)"].min() if not competitor_rows.empty else None
    competitor_median = competitor_rows["Price / Day (AED)"].median() if not competitor_rows.empty else None
    recommended_price = (
        round(float(competitor_floor) * (1 + margin_pct), 2) if competitor_floor is not None else None
    )

    budget_rank = "-"
    if budget_price is not None:
        total_market_rows = market_rows["Price / Day (AED)"].dropna()
        if not total_market_rows.empty:
            rank = int((total_market_rows < budget_price).sum() + 1)
            budget_rank = f"{rank}/{len(total_market_rows)}"

    return {
        "budget_price": budget_price,
        "competitor_floor": competitor_floor,
        "competitor_median": competitor_median,
        "recommended_price": recommended_price,
        "budget_rank": budget_rank,
    }


def build_chart_rows(market_rows: pd.DataFrame, budget_price: float | None) -> pd.DataFrame:
    if market_rows.empty:
        return market_rows

    aggregations = {
        "Price / Day (AED)": "min",
        "Total Price (AED)": "min",
    }
    if "Car" in market_rows.columns:
        aggregations["Car"] = lambda series: sorted({str(value).strip() for value in series if pd.notna(value) and str(value).strip()})

    chart_rows = market_rows.groupby(["Supplier", "Role"], as_index=False).agg(aggregations)
    chart_rows = chart_rows.rename(columns={"Price / Day (AED)": "price_per_day_aed"})

    if "Car" in chart_rows.columns:
        chart_rows["full_car_list"] = chart_rows["Car"].apply(lambda cars: ", ".join(cars))
        chart_rows["car_label"] = chart_rows["Car"].apply(
            lambda cars: (
                cars[0]
                if len(cars) == 1
                else ", ".join(cars[:2]) if len(cars) <= 2 else f"{cars[0]}, {cars[1]} +{len(cars) - 2}"
            )
        )
    else:
        chart_rows["full_car_list"] = ""
        chart_rows["car_label"] = ""

    chart_rows["display_supplier"] = chart_rows.apply(
        lambda row: row["Supplier"] if not row["car_label"] else f"{row['Supplier']}<br>{row['car_label']}",
        axis=1,
    )

    chart_rows["distance_pct"] = None
    chart_rows["distance_label"] = ""

    if budget_price is not None and budget_price > 0:
        chart_rows["distance_pct"] = (
            (chart_rows["price_per_day_aed"] - budget_price) / budget_price * 100
        )
        chart_rows["distance_label"] = chart_rows.apply(
            lambda row: "Budget"
            if row["Role"] == "Budget"
            else f"{row['distance_pct']:+.0f}%",
            axis=1,
        )
    else:
        chart_rows["distance_label"] = chart_rows["Role"].apply(
            lambda role: "Budget" if role == "Budget" else ""
        )

    chart_rows["color"] = chart_rows["Role"].apply(
        lambda role: "#D62828" if role == "Budget" else "#9DB4C0"
    )
    chart_rows = chart_rows.sort_values("price_per_day_aed", ascending=True).reset_index(drop=True)
    return chart_rows


def build_market_chart(chart_rows: pd.DataFrame, budget_price: float | None, scenario_title: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=chart_rows["display_supplier"],
            y=chart_rows["price_per_day_aed"],
            marker_color=chart_rows["color"],
            text=chart_rows["distance_label"],
            textposition="outside",
            customdata=chart_rows[["Role", "full_car_list"]],
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Price / Day: AED %{y:.0f}<br>"
                "Role: %{customdata[0]}<br>"
                "Cars: %{customdata[1]}<extra></extra>"
            ),
        )
    )

    if budget_price is not None:
        fig.add_hline(
            y=budget_price,
            line_width=2,
            line_dash="dash",
            line_color="#D62828",
            annotation_text=f"Budget: AED {round(float(budget_price)):.0f}",
            annotation_position="top left",
        )

    fig.update_layout(
        title=scenario_title,
        xaxis_title="Supplier",
        yaxis_title="Price Per Day (AED)",
        height=560,
        showlegend=False,
        margin=dict(l=20, r=20, t=80, b=20),
    )
    return fig


def build_trend_chart(
    scoped_rows: pd.DataFrame,
    mode: str,
    selected_duration: int,
    selected_lead: int,
    title_prefix: str,
) -> go.Figure:
    if mode == "Rental length":
        x_dimension = "duration_days"
        x_values = [1, 7, 30]
        fixed_dimension = "lead_time_days"
        fixed_value = selected_lead
        x_labels = {1: "1 Day", 7: "1 Week", 30: "1 Month"}
        title_suffix = f"at {SCENARIO_LABELS[(1, selected_lead)].split(' / ')[1]}"
    else:
        x_dimension = "lead_time_days"
        x_values = [0, 7, 30]
        fixed_dimension = "duration_days"
        fixed_value = selected_duration
        x_labels = {0: "Today", 7: "+7 Days", 30: "+30 Days"}
        title_suffix = f"for {SCENARIO_LABELS[(selected_duration, 0)].split(' / ')[0]}"

    filtered = scoped_rows[scoped_rows[fixed_dimension] == fixed_value].copy()
    fig = go.Figure()

    if filtered.empty:
        fig.update_layout(
            title=f"{title_prefix} | No trend data",
            height=420,
            xaxis_title=mode,
            yaxis_title="Price Per Day (AED)",
        )
        return fig

    for supplier in sorted(filtered["supplier"].dropna().astype(str).unique()):
        supplier_rows = filtered[filtered["supplier"] == supplier].copy()
        point_rows = []
        for x_value in x_values:
            subset = supplier_rows[supplier_rows[x_dimension] == x_value]
            if subset.empty:
                continue
            point_rows.append(
                {
                    "x_value": x_value,
                    "label": x_labels[x_value],
                    "price": subset["price_per_day_aed"].min(),
                }
            )

        if not point_rows:
            continue

        supplier_df = pd.DataFrame(point_rows).sort_values("x_value")
        is_budget = "budget" in supplier.strip().lower()
        fig.add_trace(
            go.Scatter(
                x=supplier_df["label"],
                y=supplier_df["price"],
                mode="lines+markers",
                name=supplier,
                line=dict(width=4 if is_budget else 2, color="#D62828" if is_budget else None),
                marker=dict(size=10 if is_budget else 7),
                hovertemplate="<b>%{fullData.name}</b><br>Price / Day: AED %{y:.0f}<extra></extra>",
            )
        )

    fig.update_layout(
        title=f"{title_prefix} | {mode} trend {title_suffix}",
        height=420,
        xaxis_title=mode,
        yaxis_title="Price Per Day (AED)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=20, r=20, t=80, b=20),
    )
    return fig


data, corrupted_files = load_dashboard_data()
check_password()
car_to_acriss, acriss_to_cars = load_acriss_mapping()
data = attach_acriss_codes(data, car_to_acriss)

if data.empty:
    st.error(
        "No target pricing rows are available yet. The app expects airport searches for 1, 7, and 30 day rentals with lead times of 0, 7, and 30 days."
    )
    st.stop()

collection_dates = get_available_collection_dates(data)

st.sidebar.header("Controls")
selected_collection_date = st.sidebar.selectbox(
    "Collection date",
    options=collection_dates,
    index=len(collection_dates) - 1,
)

st.markdown(f"**Today's Date:** {format_long_date(selected_collection_date)}")

margin_pct_display = st.sidebar.slider(
    "Margin above competitor floor (%)",
    min_value=0,
    max_value=100,
    value=15,
    step=1,
    help="Recommendation rule: competitor floor * (1 + margin).",
)
margin_pct = margin_pct_display / 100

available_cars = get_available_cars(data, selected_collection_date)
if not available_cars:
    st.error("No exact car models are available for the selected collection date.")
    st.stop()

duration_col, lead_col = st.columns(2)
with duration_col:
    selected_duration = st.radio(
        "Rental length",
        options=[1, 7, 30],
        horizontal=True,
        format_func=lambda value: {1: "1 Day", 7: "1 Week", 30: "1 Month"}[value],
    )
with lead_col:
    selected_lead = st.radio(
        "Booking timing",
        options=[0, 7, 30],
        horizontal=True,
        format_func=lambda value: {0: "Today", 7: "+7 Days", 30: "+30 Days"}[value],
    )

scenario_label = SCENARIO_LABELS[(selected_duration, selected_lead)]
benchmark_tabs = st.tabs(["Exact Car", "Car Category"])

with benchmark_tabs[0]:
    selected_car = st.selectbox("Car model", options=available_cars)

    matrix = build_pricing_matrix(
        data=data,
        collection_date_str=selected_collection_date,
        car_name=selected_car,
        margin_pct=margin_pct,
    )

    selected_scenario = matrix[
        (matrix["duration_days"] == selected_duration) & (matrix["lead_time_days"] == selected_lead)
    ].iloc[0]

    market_rows = get_market_rows_for_scenario(
        data=data,
        collection_date_str=selected_collection_date,
        car_name=selected_car,
        scenario_key=selected_scenario["scenario_key"],
    ).rename(
        columns={
            "market_role": "Role",
            "supplier": "Supplier",
            "car_name": "Car",
            "pickup_date_str": "Pickup Date",
            "duration_days": "Duration Days",
            "lead_time_days": "Lead Time Days",
            "price_per_day_aed": "Price / Day (AED)",
            "total_price_aed": "Total Price (AED)",
            "pickup_location": "Pickup Location",
            "source_file": "Source File",
            "sheet_name": "Sheet",
        }
    )

    scenario_title = f"{selected_car} | {scenario_label}"

    if market_rows.empty:
        st.warning("No exact-match market rows are available for this scenario.")
    else:
        budget_price = selected_scenario["budget_price_per_day"]
        competitor_floor = selected_scenario["competitor_floor_per_day"]
        competitor_median = selected_scenario["competitor_median_per_day"]
        recommended_price = selected_scenario["recommended_price_per_day"]
        budget_rank = selected_scenario["budget_rank"] or "-"

        chart_rows = build_chart_rows(market_rows, budget_price)
        fig = build_market_chart(chart_rows, budget_price, scenario_title)

        summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
        summary_col1.metric("Budget Price / Day", format_currency(budget_price))
        summary_col2.metric("Market Floor / Day", format_currency(competitor_floor))
        summary_col3.metric("Market Median / Day", format_currency(competitor_median))
        summary_col4.metric("Budget Rank", budget_rank)

        st.plotly_chart(fig, use_container_width=True)

        if budget_price is None:
            st.info("Budget is not present in this exact-match market snapshot.")
        else:
            floor_gap_pct = ((budget_price - competitor_floor) / competitor_floor * 100) if competitor_floor and competitor_floor > 0 else None
            median_gap_pct = ((budget_price - competitor_median) / competitor_median * 100) if competitor_median and competitor_median > 0 else None

            summary_parts = [
                f"Budget is at {format_currency(budget_price)} per day",
                f"vs floor {format_currency(competitor_floor)} ({format_pct(floor_gap_pct)})",
                f"and median {format_currency(competitor_median)} ({format_pct(median_gap_pct)})",
            ]
            if recommended_price is not None:
                summary_parts.append(
                    f"recommended price at {margin_pct_display}% above floor: {format_currency(recommended_price)}"
                )
            st.markdown("**Benchmark Summary**")
            st.write(" | ".join(summary_parts))

        with st.expander("Market rows"):
            display_rows = market_rows[
                [
                    "Role",
                    "Supplier",
                    "Pickup Date",
                    "Duration Days",
                    "Lead Time Days",
                    "Price / Day (AED)",
                    "Total Price (AED)",
                    "Pickup Location",
                    "Source File",
                    "Sheet",
                ]
            ].reset_index(drop=True)
            st.markdown(display_rows.to_html(index=False), unsafe_allow_html=True)

        exact_trend_mode = st.radio(
            "Exact car trend view",
            ["Rental length", "Days in advance"],
            horizontal=True,
            key="exact_trend_mode",
        )
        exact_trend_fig = build_trend_chart(
            scoped_rows=data[
                (data["collection_date_str"] == selected_collection_date)
                & (data["car_name"] == selected_car)
            ],
            mode=exact_trend_mode,
            selected_duration=selected_duration,
            selected_lead=selected_lead,
            title_prefix=selected_car,
        )
        st.plotly_chart(exact_trend_fig, use_container_width=True)

with benchmark_tabs[1]:
    category_scope = data[
        (data["collection_date_str"] == selected_collection_date)
        & (data["acriss_code"].notna())
    ]
    available_categories = sorted(category_scope["acriss_code"].dropna().astype(str).unique().tolist())

    if not available_categories:
        st.warning("No ACRISS categories are available for this collection date.")
    else:
        selected_acriss = st.selectbox("Car category (ACRISS)", options=available_categories)
        cars_in_group = acriss_to_cars.get(selected_acriss, [])
        if cars_in_group:
            st.caption("Cars in this category: " + ", ".join(cars_in_group[:8]) + ("..." if len(cars_in_group) > 8 else ""))

        scenario_key = f"lead_{selected_lead}_duration_{selected_duration}"
        group_rows = category_scope[
            (category_scope["acriss_code"] == selected_acriss)
            & (category_scope["scenario_key"] == scenario_key)
        ].copy()

        if group_rows.empty:
            st.warning("No market rows are available for this category and scenario.")
        else:
            group_rows["Role"] = group_rows["supplier"].apply(
                lambda supplier: "Budget" if "budget" in str(supplier).strip().lower() else "Competitor"
            )
            market_rows = group_rows.rename(
                columns={
                    "supplier": "Supplier",
                    "car_name": "Car",
                    "pickup_date_str": "Pickup Date",
                    "duration_days": "Duration Days",
                    "lead_time_days": "Lead Time Days",
                    "price_per_day_aed": "Price / Day (AED)",
                    "total_price_aed": "Total Price (AED)",
                    "pickup_location": "Pickup Location",
                    "source_file": "Source File",
                    "sheet_name": "Sheet",
                    "acriss_code": "ACRISS",
                }
            )

            summary = summarize_market_rows(market_rows, margin_pct)
            scenario_title = f"ACRISS {selected_acriss} | {scenario_label}"
            chart_rows = build_chart_rows(market_rows, summary["budget_price"])
            fig = build_market_chart(chart_rows, summary["budget_price"], scenario_title)

            summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
            summary_col1.metric("Budget Price / Day", format_currency(summary["budget_price"]))
            summary_col2.metric("Market Floor / Day", format_currency(summary["competitor_floor"]))
            summary_col3.metric("Market Median / Day", format_currency(summary["competitor_median"]))
            summary_col4.metric("Budget Rank", summary["budget_rank"])

            st.plotly_chart(fig, use_container_width=True)

            if summary["budget_price"] is None:
                st.info("Budget is not present in this category snapshot.")
            else:
                floor_gap_pct = ((summary["budget_price"] - summary["competitor_floor"]) / summary["competitor_floor"] * 100) if summary["competitor_floor"] and summary["competitor_floor"] > 0 else None
                median_gap_pct = ((summary["budget_price"] - summary["competitor_median"]) / summary["competitor_median"] * 100) if summary["competitor_median"] and summary["competitor_median"] > 0 else None
                summary_parts = [
                    f"Budget is at {format_currency(summary['budget_price'])} per day",
                    f"vs floor {format_currency(summary['competitor_floor'])} ({format_pct(floor_gap_pct)})",
                    f"and median {format_currency(summary['competitor_median'])} ({format_pct(median_gap_pct)})",
                ]
                if summary["recommended_price"] is not None:
                    summary_parts.append(
                        f"recommended price at {margin_pct_display}% above floor: {format_currency(summary['recommended_price'])}"
                    )
                st.markdown("**Benchmark Summary**")
                st.write(" | ".join(summary_parts))

            with st.expander("Market rows"):
                display_rows = market_rows[
                    [
                        "Role",
                        "Supplier",
                        "Car",
                        "ACRISS",
                        "Pickup Date",
                        "Duration Days",
                        "Lead Time Days",
                        "Price / Day (AED)",
                        "Total Price (AED)",
                        "Pickup Location",
                    ]
                ].reset_index(drop=True)
                st.markdown(display_rows.to_html(index=False), unsafe_allow_html=True)

            category_trend_mode = st.radio(
                "Category trend view",
                ["Rental length", "Days in advance"],
                horizontal=True,
                key="category_trend_mode",
            )
            category_trend_fig = build_trend_chart(
                scoped_rows=data[
                    (data["collection_date_str"] == selected_collection_date)
                    & (data["acriss_code"] == selected_acriss)
                ],
                mode=category_trend_mode,
                selected_duration=selected_duration,
                selected_lead=selected_lead,
                title_prefix=f"ACRISS {selected_acriss}",
            )
            st.plotly_chart(category_trend_fig, use_container_width=True)

st.caption(
    f"Workspace data source: {Path(ROOT_DIR).name} | Exact car and ACRISS benchmarking | Margin slider: {margin_pct_display}%"
)
