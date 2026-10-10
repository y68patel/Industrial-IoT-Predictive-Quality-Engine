"""
Data ingestion, cleaning, and transformation pipeline for Industrial IoT telemetry.
Replaces Snowflake Bronze and Silver layers with local SQLite and vectorized Pandas/NumPy.
"""

import logging
import sqlite3
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

from src.config import (
    RAW_DATA_PATH,
    DATABASE_URL,
    SQLITE_DB_PATH,
    PROCESSED_DATA_DIR,
    SENSOR_COLS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_db_engine():
    """Create and return a SQLAlchemy database engine."""
    return create_engine(DATABASE_URL)


def ingest_raw_data(csv_path=RAW_DATA_PATH) -> pd.DataFrame:
    """
    Ingest raw IoT CSV telemetry and store it in SQLite Bronze layer (raw_sensor_events).
    """
    logger.info("Loading raw IoT telemetry from %s...", csv_path)
    df_raw = pd.read_csv(csv_path)

    # Standardize column names to lowercase
    df_raw.columns = [c.strip().lower() for c in df_raw.columns]

    # Convert timestamps
    if "timestamp" in df_raw.columns:
        df_raw["event_ts"] = pd.to_datetime(df_raw["timestamp"])
    elif "event_ts" in df_raw.columns:
        df_raw["event_ts"] = pd.to_datetime(df_raw["event_ts"])

    logger.info("Loaded %d raw events with %d columns.", len(df_raw), len(df_raw.columns))

    # Persist Bronze layer into SQLite
    engine = get_db_engine()
    logger.info("Persisting Bronze layer to SQLite (table: raw_sensor_events)...")
    df_raw.to_sql("raw_sensor_events", con=engine, if_exists="replace", index=False)

    return df_raw


def decode_plc_payload(payload_series: pd.Series) -> pd.DataFrame:
    """
    Vectorized bitwise decoding of hexadecimal PLC payloads.
    0x01 (Bit 0): Emergency Stop
    0x02 (Bit 1): Motor Overheating Warning
    0x04 (Bit 2): Hydraulic Pressure Valve Open
    """
    def parse_hex(val):
        if pd.isna(val):
            return 0
        s = str(val).strip()
        try:
            return int(s, 16)
        except (ValueError, TypeError):
            return 0

    plc_ints = payload_series.apply(parse_hex).values

    emergency_stop = (np.bitwise_and(plc_ints, 1) > 0).astype(int)
    motor_overheating = (np.bitwise_and(plc_ints, 2) > 0).astype(int)
    hydraulic_valve = (np.bitwise_and(plc_ints, 4) > 0).astype(int)

    return pd.DataFrame({
        "emergency_stop": emergency_stop,
        "motor_overheating_warning": motor_overheating,
        "hydraulic_pressure_valve_open": hydraulic_valve,
    }, index=payload_series.index)


def clean_and_transform_sensor_data(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Transforms Bronze raw telemetry into Silver cleaned dataset:
    1. Deduplication on event_id.
    2. Rolling window backward imputation for missing temperatures per machine.
    3. Bitwise PLC payload decoding into boolean alert flags.
    4. Quality and failure flag standardizations.
    """
    logger.info("Executing Silver layer cleaning and transformation...")
    df = df_raw.copy()

    # 1. Deduplicate by event_id, keeping the latest record
    initial_count = len(df)
    df = df.sort_values(["event_id", "event_ts"]).drop_duplicates(subset=["event_id"], keep="last")
    deduped_count = len(df)
    logger.info("Deduplication: removed %d duplicate events (%d -> %d).", initial_count - deduped_count, initial_count, deduped_count)

    # 2. Sort by machine and timestamp
    df = df.sort_values(["machine_id", "event_ts"]).reset_index(drop=True)

    # 3. Rolling imputation for temperature (replicates Snowflake AVG OVER 5 PRECEDING)
    logger.info("Performing rolling backward imputation for missing temperature readings...")
    df["was_temperature_imputed"] = df["temperature"].isna()

    rolling_temp = (
        df.groupby("machine_id")["temperature"]
        .transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    )
    # Fill with rolling average; if still null at the start, fill with machine median
    machine_median_temp = df.groupby("machine_id")["temperature"].transform("median")
    df["temperature"] = df["temperature"].fillna(rolling_temp).fillna(machine_median_temp)

    # 4. Decode PLC hexadecimal payload
    logger.info("Decoding PLC hex payloads via bitwise masks...")
    plc_decoded = decode_plc_payload(df["plc_payload"])
    df["emergency_stop"] = plc_decoded["emergency_stop"]
    df["motor_overheating_warning"] = plc_decoded["motor_overheating_warning"]
    df["hydraulic_pressure_valve_open"] = plc_decoded["hydraulic_pressure_valve_open"]

    # 5. Standardize target & quality flags
    df["actual_failure_flag"] = df["actual_failure"].astype(bool).astype(int)
    df["bad_quality_flag"] = (df["quality"].astype(str).str.upper() == "BAD").astype(int)

    # Persist Silver layer into SQLite
    engine = get_db_engine()
    logger.info("Persisting Silver layer to SQLite (table: silver_sensor_cleaned)...")
    df.to_sql("silver_sensor_cleaned", con=engine, if_exists="replace", index=False)

    return df


def generate_curated_aggregations(df_silver: pd.DataFrame):
    """
    Generate Machine Summary and Daily Line Quality aggregations (Gold tables).
    """
    logger.info("Computing Curated Gold aggregations...")

    # Machine Quality Summary
    machine_summary = (
        df_silver.groupby("machine_id")
        .agg(
            total_events=("event_id", "count"),
            bad_quality_events=("bad_quality_flag", "sum"),
            actual_failures=("actual_failure_flag", "sum"),
            avg_temperature=("temperature", lambda x: round(x.mean(), 2)),
            avg_pressure=("pressure", lambda x: round(x.mean(), 2)),
            avg_vibration=("vibration", lambda x: round(x.mean(), 3)),
            avg_cycle_time=("cycle_time", lambda x: round(x.mean(), 3)),
            avg_parts_per_hour=("parts_per_hour", lambda x: round(x.mean(), 1)),
            emergency_stop_events=("emergency_stop", "sum"),
            motor_overheat_events=("motor_overheating_warning", "sum"),
            hydraulic_valve_open_events=("hydraulic_pressure_valve_open", "sum"),
        )
        .reset_index()
    )
    machine_summary["failure_rate_pct"] = (
        (machine_summary["actual_failures"] * 100.0 / machine_summary["total_events"]).round(2)
    )

    # Line Quality Daily
    df_silver_daily = df_silver.copy()
    df_silver_daily["production_date"] = pd.to_datetime(df_silver_daily["event_ts"]).dt.date

    daily_quality = (
        df_silver_daily.groupby(["production_date", "machine_id"])
        .agg(
            total_events=("event_id", "count"),
            bad_quality_events=("bad_quality_flag", "sum"),
            actual_failures=("actual_failure_flag", "sum"),
            avg_temperature=("temperature", lambda x: round(x.mean(), 2)),
            avg_pressure=("pressure", lambda x: round(x.mean(), 2)),
            avg_vibration=("vibration", lambda x: round(x.mean(), 3)),
            avg_cycle_time=("cycle_time", lambda x: round(x.mean(), 3)),
            avg_parts_per_hour=("parts_per_hour", lambda x: round(x.mean(), 1)),
            emergency_stop_events=("emergency_stop", "sum"),
            motor_overheat_events=("motor_overheating_warning", "sum"),
            hydraulic_valve_open_events=("hydraulic_pressure_valve_open", "sum"),
        )
        .reset_index()
    )
    daily_quality["bad_quality_rate_pct"] = (
        (daily_quality["bad_quality_events"] * 100.0 / daily_quality["total_events"]).round(2)
    )
    daily_quality["production_date"] = daily_quality["production_date"].astype(str)

    # Persist to SQLite
    engine = get_db_engine()
    logger.info("Persisting Gold tables to SQLite: dim_machine_summary & dim_daily_quality...")
    machine_summary.to_sql("dim_machine_summary", con=engine, if_exists="replace", index=False)
    daily_quality.to_sql("dim_daily_quality", con=engine, if_exists="replace", index=False)

    return machine_summary, daily_quality


def run_etl_pipeline():
    """Run full ETL from raw CSV to Silver and Gold tables."""
    df_raw = ingest_raw_data()
    df_silver = clean_and_transform_sensor_data(df_raw)
    machine_summary, daily_quality = generate_curated_aggregations(df_silver)
    logger.info("ETL Pipeline completed successfully.")
    return df_silver, machine_summary, daily_quality


if __name__ == "__main__":
    run_etl_pipeline()

