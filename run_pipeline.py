"""
Unified Pipeline Orchestrator & CLI Runner for Industrial IoT Quality Engine.
Usage:
    python run_pipeline.py --all        # Run complete end-to-end pipeline
    python run_pipeline.py --ingest     # Run ETL and populate SQLite tables
    python run_pipeline.py --train      # Train and evaluate Random Forest model
    python run_pipeline.py --dashboard  # Launch interactive Streamlit dashboard
"""

import argparse
import logging
import subprocess
import sys
import pandas as pd

from src.data_pipeline import run_etl_pipeline
from src.model_trainer import train_and_evaluate
from src.prescriptive_engine import enrich_with_prescriptive_actions
from src.sql_exporter import export_to_sql_and_powerbi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def execute_full_pipeline():
    """Run full end-to-end IoT pipeline."""
    logger.info("=" * 60)
    logger.info("STARTING INDUSTRIAL IOT PREDICTIVE QUALITY PIPELINE")
    logger.info("=" * 60)

    # Step 1: Bronze & Silver ETL into SQLite
    logger.info("\n>>> [STEP 1/4] Data Ingestion & SQL Transformations...")
    df_silver, machine_summary, daily_quality = run_etl_pipeline()

    # Step 2: Feature Engineering & Model Training
    logger.info("\n>>> [STEP 2/4] Time-Series Feature Engineering & ML Training...")
    model, test_df, metadata = train_and_evaluate()

    # Step 3: Prescriptive Actions Engine
    logger.info("\n>>> [STEP 3/4] Prescriptive Root-Cause Diagnostics & Action Mapping...")
    scored_df = enrich_with_prescriptive_actions(test_df)

    # Step 4: Persist Gold Serving Tables to SQLite & Power BI
    logger.info("\n>>> [STEP 4/4] Writing Gold Serving Layer to SQLite & Power BI...")
    export_to_sql_and_powerbi(scored_df, machine_summary, daily_quality)

    logger.info("=" * 60)
    logger.info("PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
    logger.info("  SQLite Database: Data/iot_quality.db (Tables: fact_predictions, dim_machine_summary, dim_daily_quality)")
    logger.info("  Power BI Exports: Data/powerbi/ (CSV files ready for Power BI)")
    logger.info("  Reports Saved: reports/ (Feature importance, ROC curve, Confusion matrix)")
    logger.info("  Model Saved: models/iot_rf_model.joblib")
    logger.info("=" * 60)


def launch_dashboard():
    """Launch Streamlit dashboard."""
    logger.info("Launching Streamlit Interactive Dashboard...")
    cmd = [sys.executable, "-m", "streamlit", "run", "src/dashboard.py"]
    subprocess.run(cmd)


def main():
    parser = argparse.ArgumentParser(description="Industrial IoT Predictive Quality Pipeline CLI")
    parser.add_argument("--all", action="store_true", help="Run full pipeline end-to-end")
    parser.add_argument("--ingest", action="store_true", help="Run ETL and populate SQLite Bronze/Silver tables")
    parser.add_argument("--train", action="store_true", help="Train Random Forest and evaluate")
    parser.add_argument("--dashboard", action="store_true", help="Launch interactive Streamlit dashboard")

    args = parser.parse_args()

    # Default to --all if no flag provided
    if not any([args.all, args.ingest, args.train, args.dashboard]):
        execute_full_pipeline()
    elif args.all:
        execute_full_pipeline()
    elif args.ingest:
        run_etl_pipeline()
    elif args.train:
        train_and_evaluate()
    elif args.dashboard:
        launch_dashboard()


if __name__ == "__main__":
    main()

