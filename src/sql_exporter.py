"""
SQL Serving Layer.
Persists scored predictions and dimension tables to SQLite database
and exports mirror files for Power BI reporting.
"""

import logging
import pandas as pd
from sqlalchemy import create_engine

from src.config import (
    DATABASE_URL,
    POWERBI_DIR,
    DATA_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def export_to_sql_and_powerbi(predictions_df: pd.DataFrame, machine_summary_df: pd.DataFrame, daily_quality_df: pd.DataFrame):
    """
    Saves the final Star Schema into SQLite and exports CSV copies for Power BI.
    """
    engine = create_engine(DATABASE_URL)

    # Columns of interest for Power BI Fact table
    fact_cols = [
        "event_id",
        "machine_id",
        "event_ts",
        "temperature",
        "pressure",
        "vibration",
        "cycle_time",
        "parts_per_hour",
        "emergency_stop",
        "motor_overheating_warning",
        "hydraulic_pressure_valve_open",
        "actual_failure_flag",
        "failure_within_horizon",
        "predicted_failure_probability",
        "predicted_risk_level",
        "maintenance_urgency",
        "primary_root_cause",
        "recommended_action",
    ]

    # Filter to existing columns
    export_fact = predictions_df[[c for c in fact_cols if c in predictions_df.columns]].copy()

    # 1. Write to SQLite database
    logger.info("Writing fact_predictions to SQLite database...")
    export_fact.to_sql("fact_predictions", con=engine, if_exists="replace", index=False)

    logger.info("Writing dim_machine_summary to SQLite database...")
    machine_summary_df.to_sql("dim_machine_summary", con=engine, if_exists="replace", index=False)

    logger.info("Writing dim_daily_quality to SQLite database...")
    daily_quality_df.to_sql("dim_daily_quality", con=engine, if_exists="replace", index=False)

    # 2. Export mirror files for Power BI
    logger.info("Exporting Power BI files to %s...", POWERBI_DIR)
    fact_csv_path = POWERBI_DIR / "fact_predictions.csv"
    export_fact.to_csv(fact_csv_path, index=False)

    summary_csv_path = POWERBI_DIR / "dim_machine_summary.csv"
    machine_summary_df.to_csv(summary_csv_path, index=False)

    daily_csv_path = POWERBI_DIR / "dim_daily_quality.csv"
    daily_quality_df.to_csv(daily_csv_path, index=False)

    # Update root Data/predictions_output.csv for backward compatibility
    legacy_pred_path = DATA_DIR / "predictions_output.csv"
    export_fact.to_csv(legacy_pred_path, index=False)

    logger.info("SQL and Power BI export completed successfully.")
    return export_fact

