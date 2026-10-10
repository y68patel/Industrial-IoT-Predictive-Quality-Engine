"""
Model training and evaluation module for the Industrial IoT Quality Engine.
Trains a balanced Random Forest classifier with time-series splitting,
generates evaluation visualizations, and serializes the model artifact.
"""

import json
import logging
import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
    roc_auc_score,
    roc_curve,
    precision_recall_curve,
    average_precision_score,
)

from src.config import (
    MODEL_PARAMS,
    MODEL_PATH,
    METADATA_PATH,
    REPORTS_DIR,
)
from src.feature_engineering import prepare_modeling_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def time_based_split(df: pd.DataFrame, feature_cols: list, test_size: float = 0.2):
    """
    Split dataset chronologically into train and test sets to prevent temporal data leakage.
    """
    df_sorted = df.sort_values("event_ts").reset_index(drop=True)
    split_idx = int(len(df_sorted) * (1 - test_size))

    train_df = df_sorted.iloc[:split_idx].copy()
    test_df = df_sorted.iloc[split_idx:].copy()

    X_train = train_df[feature_cols]
    y_train = train_df["failure_within_horizon"]

    X_test = test_df[feature_cols]
    y_test = test_df["failure_within_horizon"]

    logger.info(
        "Time-based split: Train size = %d (events up to %s), Test size = %d (events from %s)",
        len(train_df),
        train_df["event_ts"].max(),
        len(test_df),
        test_df["event_ts"].min(),
    )
    return train_df, test_df, X_train, y_train, X_test, y_test


def plot_and_save_metrics(model, X_test, y_test, feature_cols, test_probs, y_pred):
    """Generate and save visual evaluation plots in reports/."""
    # 1. Feature Importance Plot
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1][:15]  # Top 15 features

    plt.figure(figsize=(10, 6))
    plt.title("Top 15 Industrial IoT Predictive Features", fontsize=14, fontweight="bold")
    plt.barh(
        [feature_cols[i] for i in sorted_idx][::-1],
        importances[sorted_idx][::-1],
        color="#2b5c8f",
        edgecolor="black",
    )
    plt.xlabel("Gini Feature Importance", fontsize=12)
    plt.tight_layout()
    feat_img_path = REPORTS_DIR / "feature_importance.png"
    plt.savefig(feat_img_path, dpi=300)
    plt.close()
    logger.info("Saved feature importance chart to %s", feat_img_path)

    # 2. ROC Curve
    fpr, tpr, _ = roc_curve(y_test, test_probs)
    auc_val = roc_auc_score(y_test, test_probs)

    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, color="#008080", lw=2, label=f"Random Forest (AUC = {auc_val:.3f})")
    plt.plot([0, 1], [0, 1], color="grey", linestyle="--")
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel("False Positive Rate", fontsize=12)
    plt.ylabel("True Positive Rate", fontsize=12)
    plt.title("ROC Curve - Predictive Quality Engine", fontsize=14, fontweight="bold")
    plt.legend(loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    roc_img_path = REPORTS_DIR / "roc_curve.png"
    plt.savefig(roc_img_path, dpi=300)
    plt.close()
    logger.info("Saved ROC curve chart to %s", roc_img_path)

    # 3. Confusion Matrix
    cm = confusion_matrix(y_test, y_pred)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=["Normal", "Failure Soon"])
    fig, ax = plt.subplots(figsize=(6, 5))
    disp.plot(ax=ax, cmap="Blues", colorbar=False)
    plt.title("Confusion Matrix (Holdout Test Set)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    cm_img_path = REPORTS_DIR / "confusion_matrix.png"
    plt.savefig(cm_img_path, dpi=300)
    plt.close()
    logger.info("Saved confusion matrix to %s", cm_img_path)


def train_and_evaluate():
    """
    Orchestrates data prep, model fitting, metric evaluation, and artifact serialization.
    """
    model_df, feature_cols = prepare_modeling_data()

    train_df, test_df, X_train, y_train, X_test, y_test = time_based_split(
        model_df, feature_cols, test_size=0.2
    )

    logger.info("Training Balanced Random Forest Classifier (%d trees)...", MODEL_PARAMS["n_estimators"])
    model = RandomForestClassifier(**MODEL_PARAMS)
    model.fit(X_train, y_train)

    train_probs = model.predict_proba(X_train)[:, 1]
    test_probs = model.predict_proba(X_test)[:, 1]
    y_pred = (test_probs >= 0.5).astype(int)

    train_auc = roc_auc_score(y_train, train_probs)
    test_auc = roc_auc_score(y_test, test_probs)
    avg_precision = average_precision_score(y_test, test_probs)

    logger.info("Model Training Complete:")
    logger.info("  Train ROC-AUC: %.4f", train_auc)
    logger.info("  Test ROC-AUC:  %.4f", test_auc)
    logger.info("  Average Precision (PR-AUC): %.4f", avg_precision)

    report_dict = classification_report(y_test, y_pred, output_dict=True)
    logger.info("Classification Report on Test Data:\n%s", classification_report(y_test, y_pred))

    # Generate and save diagnostic visualizations
    plot_and_save_metrics(model, X_test, y_test, feature_cols, test_probs, y_pred)

    # Serialize model artifact
    logger.info("Serializing trained model to %s...", MODEL_PATH)
    joblib.dump(model, MODEL_PATH)

    # Save metadata & configuration
    metadata = {
        "model_type": "RandomForestClassifier",
        "model_params": MODEL_PARAMS,
        "feature_columns": feature_cols,
        "metrics": {
            "train_roc_auc": round(float(train_auc), 4),
            "test_roc_auc": round(float(test_auc), 4),
            "test_pr_auc": round(float(avg_precision), 4),
            "classification_report": report_dict,
        },
    }
    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=4)
    logger.info("Saved feature metadata and model metrics to %s", METADATA_PATH)

    # Attach predictions to test dataframe
    test_df["predicted_failure_probability"] = test_probs
    test_df["predicted_failure_class"] = y_pred

    return model, test_df, metadata


if __name__ == "__main__":
    train_and_evaluate()

