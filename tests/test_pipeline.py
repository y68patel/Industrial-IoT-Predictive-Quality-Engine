"""
Unit and integration tests for the Industrial IoT Pipeline.
"""

import numpy as np
import pandas as pd
import pytest

from src.data_pipeline import decode_plc_payload, clean_and_transform_sensor_data
from src.prescriptive_engine import diagnose_root_cause_and_action


def test_decode_plc_payload():
    """Verify bitwise decoding logic for PLC hexadecimal strings."""
    payloads = pd.Series(["0x00", "0x01", "0x02", "0x04", "0x07", None, "invalid"])
    decoded = decode_plc_payload(payloads)

    # 0x01 should trigger emergency_stop
    assert decoded.loc[1, "emergency_stop"] == 1
    assert decoded.loc[1, "motor_overheating_warning"] == 0
    assert decoded.loc[1, "hydraulic_pressure_valve_open"] == 0

    # 0x02 should trigger motor_overheating_warning
    assert decoded.loc[2, "emergency_stop"] == 0
    assert decoded.loc[2, "motor_overheating_warning"] == 1

    # 0x04 should trigger hydraulic_pressure_valve_open
    assert decoded.loc[3, "hydraulic_pressure_valve_open"] == 1

    # 0x07 should trigger all 3 bits (1 + 2 + 4)
    assert decoded.loc[4, "emergency_stop"] == 1
    assert decoded.loc[4, "motor_overheating_warning"] == 1
    assert decoded.loc[4, "hydraulic_pressure_valve_open"] == 1

    # None and invalid should be 0
    assert decoded.loc[5, "emergency_stop"] == 0
    assert decoded.loc[6, "emergency_stop"] == 0


def test_prescriptive_diagnosis_critical_vibration():
    """Verify diagnostic recommendation for vibration spike."""
    row = pd.Series({
        "predicted_failure_probability": 0.85,
        "vibration": 5.2,
        "vibration_dev_from_roll": 2.5,
        "emergency_stop": 0,
        "motor_overheating_warning": 0,
        "hydraulic_pressure_valve_open": 0,
    })
    risk_level, urgency, root_cause, action = diagnose_root_cause_and_action(row)

    assert risk_level == "CRITICAL"
    assert "Immediate" in urgency
    assert "Vibration" in root_cause or "Bearing" in root_cause
    assert "spindle bearings" in action.lower() or "vibration" in action.lower()


def test_prescriptive_diagnosis_nominal():
    """Verify diagnostic recommendation for normal low risk."""
    row = pd.Series({
        "predicted_failure_probability": 0.12,
        "emergency_stop": 0,
        "motor_overheating_warning": 0,
        "hydraulic_pressure_valve_open": 0,
    })
    risk_level, urgency, root_cause, action = diagnose_root_cause_and_action(row)

    assert risk_level == "LOW"
    assert "Routine" in urgency
    assert "Nominal" in root_cause

