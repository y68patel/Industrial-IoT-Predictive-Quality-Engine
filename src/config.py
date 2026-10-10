"""
Configuration constants and paths for the Industrial IoT Engine.
"""

from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Data paths
DATA_DIR = PROJECT_ROOT / "Data"
RAW_DATA_PATH = DATA_DIR / "sample_raw_Iot_data.csv"
POWERBI_DIR = DATA_DIR / "powerbi"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Database paths
SQLITE_DB_PATH = DATA_DIR / "iot_quality.db"
DATABASE_URL = f"sqlite:///{SQLITE_DB_PATH}"

# Model & Artifact paths
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODELS_DIR / "iot_rf_model.joblib"
METADATA_PATH = MODELS_DIR / "feature_metadata.json"

# Reports directory
REPORTS_DIR = PROJECT_ROOT / "reports"

# Ensure directories exist
for directory in [DATA_DIR, POWERBI_DIR, PROCESSED_DATA_DIR, MODELS_DIR, REPORTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Feature engineering parameters
ROLLING_WINDOW = 10
TREND_SHORT_WINDOW = 3
FAILURE_HORIZON = 15  # 15 time steps ahead lead-window

# Core sensor columns
SENSOR_COLS = [
    "temperature",
    "pressure",
    "vibration",
    "cycle_time",
    "parts_per_hour",
]

# Random Forest Model hyperparameters
MODEL_PARAMS = {
    "n_estimators": 300,
    "max_depth": 12,
    "min_samples_leaf": 10,
    "random_state": 42,
    "class_weight": "balanced",
    "n_jobs": -1,
}

# Risk level thresholds for probabilities
RISK_THRESHOLDS = {
    "low": 0.33,
    "medium": 0.66,
}

