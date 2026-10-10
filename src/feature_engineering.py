"""
Feature engineering module for Industrial IoT Predictive Quality.
Calculates time-series rolling aggregations, degradation slopes, baseline deviations,
and forward-looking lead-horizon failure labels.
"""

import logging
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

from src.config import (
    DATABASE_URL,
    ROLLING_WINDOW,
    TREND_SHORT_WINDOW,
    FAILURE_HORIZON,
    SENSOR_COLS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_silver_data() -> pd.DataFrame:
    """Load cleaned silver telemetry from SQLite database."""
    engine = create_engine(DATABASE_URL)
    query = """
        SELECT *
        FROM silver_sensor_cleaned
        ORDER BY machine_id, event_ts ASC
    """
    logger.info("Loading silver data from SQLite...")
    df = pd.read_sql(query, con=engine)
    df["event_ts"] = pd.to_datetime(df["event_ts"])
    return df


def engineer_features(df: pd.DataFrame):
    """
    Computes time-series rolling metrics and future lead-horizon labels:
    1. Rolling Mean (10 steps)
    2. Rolling Standard Deviation (10 steps)
    3. Short vs. Long Trend (3 steps vs 10 steps)
    4. Deviation from recent baseline (Current reading - Rolling Mean)
    5. Target label: FAILURE_WITHIN_HORIZON (15 steps lookahead)
    """
    logger.info("Engineering rolling time-series features across sensor variables...")
    df = df.sort_values(["machine_id", "event_ts"]).copy()

    feature_cols = list(SENSOR_COLS)

    for col in SENSOR_COLS:
        grouped = df.groupby("machine_id")[col]

        roll_mean_col = f"{col}_roll_mean"
        roll_std_col = f"{col}_roll_std"
        trend_col = f"{col}_trend"
        dev_col = f"{col}_dev_from_roll"

        # Shift(1) ensures we strictly use past observations to prevent lookahead leakage
        df[roll_mean_col] = grouped.transform(
            lambda s: s.shift(1).rolling(window=ROLLING_WINDOW, min_periods=3).mean()
        )
        df[roll_std_col] = grouped.transform(
            lambda s: s.shift(1).rolling(window=ROLLING_WINDOW, min_periods=3).std()
        )

        short_mean = grouped.transform(
            lambda s: s.shift(1).rolling(window=TREND_SHORT_WINDOW, min_periods=2).mean()
        )
        df[trend_col] = short_mean - df[roll_mean_col]
        df[dev_col] = df[col] - df[roll_mean_col]

        feature_cols.extend([roll_mean_col, roll_std_col, trend_col, dev_col])

    # Include PLC binary alert flags as features
    plc_cols = ["emergency_stop", "motor_overheating_warning", "hydraulic_pressure_valve_open"]
    for col in plc_cols:
        if col in df.columns:
            feature_cols.append(col)

    # Future Failure Label: lookahead window of FAILURE_HORIZON
    logger.info("Constructing lead-horizon target label (horizon=%d time steps)...", FAILURE_HORIZON)
    df["failure_within_horizon"] = (
        df.groupby("machine_id")["actual_failure_flag"]
        .transform(
            lambda s: s[::-1].rolling(FAILURE_HORIZON, min_periods=1).max()[::-1]
        )
    )

    # Filter rows with complete feature history
    model_df = df.dropna(subset=feature_cols).copy()
    logger.info("Generated %d features across %d records.", len(feature_cols), len(model_df))

    return model_df, feature_cols


def prepare_modeling_data():
    """End-to-end data preparation for model training."""
    df_silver = load_silver_data()
    model_df, feature_cols = engineer_features(df_silver)
    return model_df, feature_cols


if __name__ == "__main__":
    model_df, feature_cols = prepare_modeling_data()
    print("Features engineered successfully:", len(feature_cols))

