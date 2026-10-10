"""
Interactive Industrial IoT Fleet Monitoring & Digital Twin Dashboard.
Provides real-time plant KPIs, machine telemetry drill-downs, and a 'What-If' ML simulator.
"""

import json
import sqlite3
import joblib
import numpy as np
import pandas as pd
import streamlit as st

from src.config import (
    SQLITE_DB_PATH,
    MODEL_PATH,
    METADATA_PATH,
    SENSOR_COLS,
)
from src.prescriptive_engine import diagnose_root_cause_and_action

st.set_page_config(
    page_title="Industrial IoT Predictive Quality Engine",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data
def load_data():
    """Load latest predictions and machine summaries from SQLite database."""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    try:
        fact_df = pd.read_sql("SELECT * FROM fact_predictions ORDER BY event_ts DESC", conn)
        summary_df = pd.read_sql("SELECT * FROM dim_machine_summary", conn)
        daily_df = pd.read_sql("SELECT * FROM dim_daily_quality", conn)
    except Exception as e:
        st.error(f"Error loading tables from SQLite: {e}. Please run the pipeline first.")
        fact_df, summary_df, daily_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

    if not fact_df.empty and "event_ts" in fact_df.columns:
        fact_df["event_ts"] = pd.to_datetime(fact_df["event_ts"])

    return fact_df, summary_df, daily_df


@st.cache_resource
def load_model():
    """Load serialized Random Forest model and metadata."""
    if MODEL_PATH.exists() and METADATA_PATH.exists():
        model = joblib.load(MODEL_PATH)
        with open(METADATA_PATH, "r") as f:
            meta = json.load(f)
        return model, meta
    return None, None


fact_df, summary_df, daily_df = load_data()
model, metadata = load_model()

# Custom Header Styling
st.markdown(
    """
    <div style="background: linear-gradient(135deg, #1f4068, #162447); padding: 22px; border-radius: 10px; margin-bottom: 25px;">
        <h1 style="color: #ffffff; margin: 0; font-size: 28px;">🏭 Industrial IoT Predictive Quality Engine</h1>
        <p style="color: #e4e4e4; margin: 5px 0 0 0; font-size: 15px;">Real-Time Machine Fleet Telemetry, Predictive Anomaly Detection & Prescriptive Maintenance</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if fact_df.empty:
    st.warning("⚠️ No prediction data found in SQLite database. Please run `python run_pipeline.py --all` to process telemetry and train the model.")
    st.stop()

# Sidebar Navigation
st.sidebar.image("https://img.icons8.com/fluency/96/manufacturing.png", width=64)
st.sidebar.title("Navigation")
view_mode = st.sidebar.radio(
    "Select View:",
    ["📊 Fleet Overview & KPIs", "🔍 Machine Telemetry Deep-Dive", "🧪 'What-If' Digital Twin Simulator", "📑 Model Evaluation & Docs"],
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🗄️ Database Info")
st.sidebar.info(f"**Backend:** SQLite (`{SQLITE_DB_PATH.name}`)\n\n**Total Events:** {len(fact_df):,}\n**Machines Monitored:** {fact_df['machine_id'].nunique()}")

# ==========================================================
# VIEW 1: FLEET OVERVIEW & KPIS
# ==========================================================
if view_mode == "📊 Fleet Overview & KPIs":
    st.subheader("Plant Fleet Health & Alert Monitor")

    # Get latest status per machine
    latest_per_machine = fact_df.sort_values("event_ts").groupby("machine_id").last().reset_index()

    total_machines = len(latest_per_machine)
    critical_count = (latest_per_machine["predicted_risk_level"] == "CRITICAL").sum()
    high_count = (latest_per_machine["predicted_risk_level"] == "HIGH").sum()
    nominal_count = (latest_per_machine["predicted_risk_level"] == "LOW").sum()
    healthy_pct = round((nominal_count / total_machines) * 100, 1) if total_machines > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Machines Active", f"{total_machines}")
    col2.metric("Critical Risk Alerts", f"{critical_count}", delta=f"-{critical_count}" if critical_count > 0 else "0", delta_color="inverse")
    col3.metric("High Risk Warnings", f"{high_count}", delta=f"-{high_count}" if high_count > 0 else "0", delta_color="inverse")
    col4.metric("Fleet Health Index", f"{healthy_pct}%", delta=f"{healthy_pct - 90:.1f}%")

    st.markdown("---")

    # Actionable Work-Order Table
    st.markdown("### 🛠️ Active Maintenance Work Orders & Recommendations")
    risk_filter = st.multiselect(
        "Filter by Risk Level:",
        ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        default=["CRITICAL", "HIGH", "MEDIUM"],
    )

    filtered_machines = latest_per_machine[latest_per_machine["predicted_risk_level"].isin(risk_filter)].copy()
    filtered_machines = filtered_machines.sort_values("predicted_failure_probability", ascending=False)

    display_cols = [
        "machine_id",
        "predicted_risk_level",
        "predicted_failure_probability",
        "maintenance_urgency",
        "primary_root_cause",
        "recommended_action",
    ]

    st.dataframe(
        filtered_machines[display_cols].style.format({
            "predicted_failure_probability": "{:.1%}",
        }).map(
            lambda val: "background-color: #ffcccc; color: #990000; font-weight: bold;" if val == "CRITICAL"
            else ("background-color: #fff2cc; color: #996600; font-weight: bold;" if val == "HIGH"
            else ("background-color: #e6f3ff; color: #004080;" if val == "MEDIUM" else "")),
            subset=["predicted_risk_level"],
        ),
        use_container_width=True,
        height=320,
    )

    # Historical Daily Quality Trend
    if not daily_df.empty:
        st.markdown("### 📈 Daily Production Quality & Defect Rate")
        daily_agg = daily_df.groupby("production_date").agg(
            total_events=("total_events", "sum"),
            bad_events=("bad_quality_events", "sum"),
            failures=("actual_failures", "sum"),
        ).reset_index()
        daily_agg["defect_rate_pct"] = (daily_agg["bad_events"] * 100.0 / daily_agg["total_events"]).round(2)

        st.line_chart(daily_agg.set_index("production_date")[["defect_rate_pct", "failures"]])

# ==========================================================
# VIEW 2: MACHINE TELEMETRY DEEP-DIVE
# ==========================================================
elif view_mode == "🔍 Machine Telemetry Deep-Dive":
    st.subheader("Machine Telemetry & Anomaly Analysis")

    machine_list = sorted(fact_df["machine_id"].unique())
    selected_machine = st.selectbox("Select Machine for Inspection:", machine_list)

    mach_data = fact_df[fact_df["machine_id"] == selected_machine].sort_values("event_ts").reset_index(drop=True)
    latest_rec = mach_data.iloc[-1]

    # Machine header card
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Machine ID", selected_machine)
    c2.metric("Failure Probability", f"{latest_rec['predicted_failure_probability']:.1%}")
    c3.metric("Current Risk Level", latest_rec["predicted_risk_level"])
    c4.metric("Urgency", latest_rec["maintenance_urgency"])

    st.info(f"**Recommended Action:** {latest_rec['recommended_action']}\n\n**Primary Root Cause:** {latest_rec['primary_root_cause']}")

    st.markdown("#### Sensor Telemetry Time-Series")
    chart_cols = st.multiselect(
        "Sensors to Plot:",
        ["temperature", "pressure", "vibration", "cycle_time", "parts_per_hour"],
        default=["temperature", "vibration", "pressure"],
    )

    if chart_cols:
        st.line_chart(mach_data.set_index("event_ts")[chart_cols].tail(100))

    st.markdown("#### Failure Risk Probability Over Time")
    st.line_chart(mach_data.set_index("event_ts")["predicted_failure_probability"].tail(100))

# ==========================================================
# VIEW 3: "WHAT-IF" DIGITAL TWIN SIMULATOR
# ==========================================================
elif view_mode == "🧪 'What-If' Digital Twin Simulator":
    st.subheader("Digital Twin Simulation & Stress Tester")
    st.write("Adjust sensor parameters and alerts below to evaluate how the trained Machine Learning model predicts failure probabilities in real-time.")

    if model is None or metadata is None:
        st.error("Trained model artifact not found. Please run the training pipeline first.")
        st.stop()

    feature_cols = metadata["feature_columns"]

    sim_col1, sim_col2, sim_col3 = st.columns(3)
    with sim_col1:
        st.markdown("**Continuous Telemetry**")
        sim_temp = st.slider("Temperature (°C)", 20.0, 120.0, 65.0, 0.5)
        sim_press = st.slider("Pressure (bar)", 30.0, 160.0, 75.0, 1.0)
        sim_vib = st.slider("Vibration (mm/s)", 0.5, 8.0, 2.5, 0.1)

    with sim_col2:
        st.markdown("**Production Speed & Cycle**")
        sim_cycle = st.slider("Cycle Time (sec)", 10.0, 60.0, 25.0, 0.5)
        sim_pph = st.slider("Parts Per Hour", 50.0, 400.0, 200.0, 5.0)

    with sim_col3:
        st.markdown("**PLC Hardware Flags**")
        sim_estop = st.checkbox("Emergency Stop Active", False)
        sim_overheat = st.checkbox("Motor Overheating Warning", False)
        sim_valve = st.checkbox("Hydraulic Valve Open", False)

    # Build input feature dictionary with baseline estimations
    input_dict = {
        "temperature": sim_temp,
        "pressure": sim_press,
        "vibration": sim_vib,
        "cycle_time": sim_cycle,
        "parts_per_hour": sim_pph,
        "temperature_roll_mean": 60.0,
        "temperature_roll_std": 3.0,
        "temperature_trend": sim_temp - 60.0,
        "temperature_dev_from_roll": sim_temp - 60.0,
        "pressure_roll_mean": 70.0,
        "pressure_roll_std": 5.0,
        "pressure_trend": sim_press - 70.0,
        "pressure_dev_from_roll": sim_press - 70.0,
        "vibration_roll_mean": 2.2,
        "vibration_roll_std": 0.3,
        "vibration_trend": sim_vib - 2.2,
        "vibration_dev_from_roll": sim_vib - 2.2,
        "cycle_time_roll_mean": 25.0,
        "cycle_time_roll_std": 2.0,
        "cycle_time_trend": sim_cycle - 25.0,
        "cycle_time_dev_from_roll": sim_cycle - 25.0,
        "parts_per_hour_roll_mean": 200.0,
        "parts_per_hour_roll_std": 10.0,
        "parts_per_hour_trend": sim_pph - 200.0,
        "parts_per_hour_dev_from_roll": sim_pph - 200.0,
        "emergency_stop": int(sim_estop),
        "motor_overheating_warning": int(sim_overheat),
        "hydraulic_pressure_valve_open": int(sim_valve),
    }

    # Format vector into DataFrame matching exact training feature columns
    sim_df = pd.DataFrame([input_dict])
    for col in feature_cols:
        if col not in sim_df.columns:
            sim_df[col] = 0.0

    X_sim = sim_df[feature_cols]

    sim_prob = float(model.predict_proba(X_sim)[0, 1])
    sim_row = pd.Series(input_dict)
    sim_row["predicted_failure_probability"] = sim_prob

    sim_risk, sim_urgency, sim_cause, sim_rec = diagnose_root_cause_and_action(sim_row)

    st.markdown("---")
    st.markdown("### 🎯 Real-Time Simulation Result")
    r1, r2, r3 = st.columns(3)

    r1.metric("Predicted Failure Probability", f"{sim_prob:.1%}")
    r2.metric("Simulated Risk Level", sim_risk)
    r3.metric("Urgency Level", sim_urgency)

    st.progress(sim_prob)

    if sim_risk in ["CRITICAL", "HIGH"]:
        st.error(f"🚨 **Root Cause Detected:** {sim_cause}\n\n**Action Plan:** {sim_rec}")
    elif sim_risk == "MEDIUM":
        st.warning(f"⚠️ **Notice:** {sim_cause}\n\n**Action Plan:** {sim_rec}")
    else:
        st.success(f"✅ **Normal Status:** Machine operational within nominal tolerances.")

# ==========================================================
# VIEW 4: MODEL EVALUATION & DOCS
# ==========================================================
elif view_mode == "📑 Model Evaluation & Docs":
    st.subheader("Model Validation & Performance Report")

    if metadata and "metrics" in metadata:
        m = metadata["metrics"]
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Holdout Test ROC-AUC", f"{m['test_roc_auc']:.3f}")
        mc2.metric("Train ROC-AUC", f"{m['train_roc_auc']:.3f}")
        mc3.metric("Precision-Recall PR-AUC", f"{m['test_pr_auc']:.3f}")

    from src.config import REPORTS_DIR
    feat_img = REPORTS_DIR / "feature_importance.png"
    roc_img = REPORTS_DIR / "roc_curve.png"
    cm_img = REPORTS_DIR / "confusion_matrix.png"

    tab_eval1, tab_eval2, tab_eval3 = st.tabs(["Feature Importance", "ROC Curve", "Confusion Matrix"])
    with tab_eval1:
        if feat_img.exists():
            st.image(str(feat_img), use_container_width=True)
    with tab_eval2:
        if roc_img.exists():
            st.image(str(roc_img), use_container_width=True)
    with tab_eval3:
        if cm_img.exists():
            st.image(str(cm_img), use_container_width=True)

