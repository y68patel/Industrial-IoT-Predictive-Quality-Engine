"""
Prescriptive Maintenance Engine.
Analyzes model failure predictions, identifies primary root-cause telemetry anomalies,
and generates human-readable maintenance recommendations and urgency ratings for Power BI.
"""

import logging
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def diagnose_root_cause_and_action(row: pd.Series) -> tuple:
    """
    Diagnoses primary failure driver from sensor readings and PLC flags,
    and returns (risk_level, urgency, primary_driver, recommended_action).
    """
    prob = row.get("predicted_failure_probability", 0.0)

    # Risk level categorization
    if prob >= 0.70:
        risk_level = "CRITICAL"
        urgency = "Immediate (< 1 hr)"
    elif prob >= 0.50:
        risk_level = "HIGH"
        urgency = "Urgent (< 4 hrs)"
    elif prob >= 0.33:
        risk_level = "MEDIUM"
        urgency = "Next Shift (< 12 hrs)"
    else:
        risk_level = "LOW"
        urgency = "Routine Monitoring"
        return risk_level, urgency, "None (Nominal Operation)", "Maintain scheduled preventive maintenance"

    # Evaluate specific sensor anomalies and PLC alerts
    emergency_stop = row.get("emergency_stop", 0) == 1
    motor_overheat = row.get("motor_overheating_warning", 0) == 1
    valve_open = row.get("hydraulic_pressure_valve_open", 0) == 1

    vib_dev = row.get("vibration_dev_from_roll", 0.0)
    temp_dev = row.get("temperature_dev_from_roll", 0.0)
    press_dev = row.get("pressure_dev_from_roll", 0.0)
    cycle_dev = row.get("cycle_time_dev_from_roll", 0.0)

    # Rule-based diagnostic hierarchy
    if emergency_stop:
        primary_driver = "Emergency Stop Tripped"
        action = "Verify safety interlock, clear workstation blockage, and reset E-stop."
    elif motor_overheat or temp_dev > 15.0:
        primary_driver = "Motor / Thermal Overheating"
        action = "Check motor coolant levels, inspect heat sinks, and inspect stator coil insulation."
    elif valve_open or press_dev > 20.0:
        primary_driver = "Hydraulic Pressure Spike / Valve Fault"
        action = "Inspect hydraulic bypass valve, check line filters, and verify regulator pressure."
    elif vib_dev > 1.2 or row.get("vibration", 0) > 4.5:
        primary_driver = "Excessive Vibration / Spindle Bearing Wear"
        action = "Inspect spindle bearings, verify shaft alignment, and lubricate mechanical drive."
    elif cycle_dev > 8.0:
        primary_driver = "Cycle Time Degradation / Tool Wear"
        action = "Inspect cutting tool wear, verify workpiece feed-rate, and clean conveyor guide rails."
    else:
        primary_driver = "Multi-Sensor Health Degradation"
        action = "Conduct multi-point diagnostic check on electrical drive, lubrication, and sensors."

    return risk_level, urgency, primary_driver, action


def enrich_with_prescriptive_actions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriches predictions with actionable prescriptive maintenance columns for Power BI.
    """
    logger.info("Generating prescriptive maintenance diagnosis and action recommendations...")
    df_out = df.copy()

    diagnoses = df_out.apply(diagnose_root_cause_and_action, axis=1)

    df_out["predicted_risk_level"] = [d[0] for d in diagnoses]
    df_out["maintenance_urgency"] = [d[1] for d in diagnoses]
    df_out["primary_root_cause"] = [d[2] for d in diagnoses]
    df_out["recommended_action"] = [d[3] for d in diagnoses]

    logger.info("Enriched %d records with prescriptive recommendations.", len(df_out))
    return df_out

