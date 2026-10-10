# Power BI Setup & Dashboard Guide

This guide walks you through connecting **Power BI Desktop** to the **Industrial IoT Predictive Quality Engine** database and building a production-grade operations dashboard.

---

## 1. Connecting Power BI to the Data

You can connect Power BI using either of two methods:

### Method A: Connect Directly to SQLite Database (Recommended for SQL Showcase)
1. In Power BI Desktop, click **Get Data** $\rightarrow$ **More...** $\rightarrow$ **ODBC**.
2. Select or configure your SQLite3 DSN (or connection string: `Driver={SQLite3 ODBC Driver};Database=C:\path\to\Industrial-IoT-Predictive-Quality-Engine\Data\iot_quality.db;`).
3. Under **Advanced Options**, you can either select the tables directly or write custom SQL statements:
   ```sql
   SELECT 
       event_id,
       machine_id,
       event_ts,
       temperature,
       pressure,
       vibration,
       cycle_time,
       parts_per_hour,
       predicted_failure_probability,
       predicted_risk_level,
       maintenance_urgency,
       primary_root_cause,
       recommended_action
   FROM fact_predictions;
   ```

### Method B: Connect via Clean Folder Connector (Fastest & Zero Driver Setup)
1. In Power BI Desktop, click **Get Data** $\rightarrow$ **Folder** (or **Text/CSV**).
2. Point to the `Industrial-IoT-Predictive-Quality-Engine/Data/powerbi/` folder.
3. Import the 3 pre-engineered tables:
   - `fact_predictions.csv`
   - `dim_machine_summary.csv`
   - `dim_daily_quality.csv`

---

## 2. Star Schema Data Model

In Power BI **Model View**, establish the following relationships:

```
          ┌──────────────────────────────────┐
          │       dim_machine_summary        │
          │──────────────────────────────────│
          │ 🔑 machine_id (1)                │
          │    avg_temperature               │
          │    avg_vibration                 │
          │    failure_rate_pct              │
          └─────────────────┬────────────────┘
                            │ (1 to Many)
                            ▼
          ┌──────────────────────────────────┐
          │         fact_predictions         │
          │──────────────────────────────────│
          │    event_id                      │
          │ 🔑 machine_id (*)                │
          │ 🔑 event_ts                      │
          │    temperature                   │
          │    vibration                     │
          │    predicted_failure_probability │
          │    predicted_risk_level          │
          │    recommended_action            │
          └─────────────────┬────────────────┘
                            ▲
                            │ (Many to 1)
          ┌─────────────────┴────────────────┐
          │        dim_daily_quality         │
          │──────────────────────────────────│
          │ 🔑 production_date (1)           │
          │    bad_quality_rate_pct          │
          │    total_events                  │
          └──────────────────────────────────┘
```

---

## 3. Ready-to-Use DAX Measures

Create a new table named `_Measures` in Power BI and paste the following DAX calculations:

### 1. Fleet Health Index (%)
```dax
Fleet Health % = 
VAR TotalMachines = DISTINCTCOUNT(fact_predictions[machine_id])
VAR AtRiskMachines = 
    CALCULATE(
        DISTINCTCOUNT(fact_predictions[machine_id]),
        fact_predictions[predicted_risk_level] IN {"CRITICAL", "HIGH"}
    )
RETURN
    DIVIDE(TotalMachines - AtRiskMachines, TotalMachines, 1) * 100
```

### 2. Critical Risk Machine Count
```dax
Critical Machines Count = 
CALCULATE(
    DISTINCTCOUNT(fact_predictions[machine_id]),
    fact_predictions[predicted_risk_level] = "CRITICAL"
)
```

### 3. High Risk Warnings
```dax
High Risk Machines Count = 
CALCULATE(
    DISTINCTCOUNT(fact_predictions[machine_id]),
    fact_predictions[predicted_risk_level] = "HIGH"
)
```

### 4. Average Predicted Failure Probability
```dax
Avg Failure Probability = 
AVERAGE(fact_predictions[predicted_failure_probability])
```

### 5. Production Defect Rate (%)
```dax
Defect Rate % = 
DIVIDE(
    SUM(dim_daily_quality[bad_quality_events]),
    SUM(dim_daily_quality[total_events]),
    0
) * 100
```

---

## 4. Recommended Dashboard Layout

| Visual Tile | Visual Type | Fields / Measures |
| :--- | :--- | :--- |
| **Top KPI Cards** | Card / KPI | `[Fleet Health %]`, `[Critical Machines Count]`, `[High Risk Machines Count]`, `[Avg Failure Probability]` |
| **Active Work Orders** | Table / Grid | Columns: `machine_id`, `predicted_risk_level`, `maintenance_urgency`, `primary_root_cause`, `recommended_action` (Conditional formatting on Risk Level) |
| **Telemetry Health Trends** | Line Chart | X-Axis: `event_ts`, Y-Axis: `temperature`, `vibration`, `predicted_failure_probability` |
| **Machine Risk Heatmap** | Matrix / Treemap | Group: `machine_id`, Values: `[Avg Failure Probability]`, Color saturation: Risk Score |
| **Quality vs Failures** | Line & Clustered Column | Shared Axis: `production_date`, Column: `total_events`, Line: `[Defect Rate %]` |

