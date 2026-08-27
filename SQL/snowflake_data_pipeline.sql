CREATE DATABASE IF NOT EXISTS INDUSTRIAL_IOT_QUALITY;

USE DATABASE INDUSTRIAL_IOT_QUALITY;


CREATE SCHEMA IF NOT EXISTS RAW;
CREATE SCHEMA IF NOT EXISTS CLEANED;
CREATE SCHEMA IF NOT EXISTS CURATED;
CREATE SCHEMA IF NOT EXISTS METADATA;

CREATE WAREHOUSE IF NOT EXISTS IOT_TASK_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE;


CREATE OR REPLACE TABLE METADATA.INGESTION_LOG(
    run_id STRING,
    pipeline_name STRING,
    source_file STRING,
    status STRING,
    started_at TIMESTAMP_NTZ,
    ended_at TIMESTAMP_NTZ,
    rows_loaded NUMBER,
    error_count NUMBER,
    message STRING
);

CREATE OR REPLACE TABLE METADATA.ERROR_LOG(
    error_id STRING,
    run_id STRING,
    source_file STRING,
    record_id STRING,
    error_type STRING,
    error_message STRING,
    error_ts TIMESTAMP_NTZ
);

CREATE OR REPLACE TABLE RAW.SENSOR_EVENTS_RAW(
    event_id STRING,
    machine_id STRING,
    event_ts TIMESTAMP_NTZ,
    temperature FLOAT,
    pressure FLOAT,
    vibration FLOAT,
    cycle_time FLOAT,
    parts_per_hour FLOAT,
    machine_status STRING,
    sensor_quality NUMBER,
    plc_payload STRING,
    quality STRING,
    actual_failure BOOLEAN,
    loaded_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE STREAM RAW.SENSOR_EVENTS_STREAM
    ON TABLE RAW.SENSOR_EVENTS_RAW;
    

CREATE OR REPLACE FILE FORMAT RAW.SENSOR_CSV_FORMAT
    TYPE = CSV
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF = ('','NULL','null')
    EMPTY_FIELD_AS_NULL = TRUE;


CREATE OR REPLACE STAGE RAW.SENSOR_STAGE
    FILE_FORMAT = RAW.SENSOR_CSV_FORMAT;


CREATE OR REPLACE PIPE RAW.SENSOR_EVENTS_PIPE AS COPY INTO RAW.SENSOR_EVENTS_RAW(
    event_id,
    machine_id,
    event_ts,
    temperature,
    pressure,
    vibration,
    cycle_time,
    parts_per_hour,
    machine_status,
    sensor_quality,
    plc_payload,
    quality,
    actual_failure
)
FROM @RAW.SENSOR_STAGE
FILE_FORMAT = RAW.SENSOR_CSV_FORMAT
ON_ERROR = CONTINUE;


SHOW PIPES IN SCHEMA RAW;

SELECT SYSTEM$PIPE_STATUS('RAW.SENSOR_EVENTS_PIPE');

ALTER PIPE RAW.SENSOR_EVENTS_PIPE REFRESH;

SELECT *
FROM TABLE(
    INFORMATION_SCHEMA.COPY_HISTORY(
        TABLE_NAME => 'RAW.SENSOR_EVENTS_RAW',
        START_TIME => DATEADD('hour', -1, CURRENT_TIMESTAMP())
    )
)
ORDER BY LAST_LOAD_TIME DESC;



LIST @RAW.SENSOR_STAGE;

COPY INTO RAW.SENSOR_EVENTS_RAW(
    event_id,
    machine_id,
    event_ts,
    temperature,
    pressure,
    vibration,
    cycle_time,
    parts_per_hour,
    machine_status,
    sensor_quality,
    plc_payload,
    quality,
    actual_failure
)
FROM @RAW.SENSOR_STAGE
FILE_FORMAT = RAW.SENSOR_CSV_FORMAT
ON_ERROR = CONTINUE;


SELECT COUNT(*) AS row_count
FROM RAW.SENSOR_EVENTS_RAW;

SELECT * FROM RAW.SENSOR_EVENTS_RAW LIMIT 20;

SELECT COUNT(*) AS missing_temperature_rows
FROM RAW.SENSOR_EVENTS_RAW
WHERE temperature IS NULL;
-- counts the number of rows where temperature is NULL

SELECT event_id, COUNT(*) AS duplicate_count
FROM RAW.SENSOR_EVENTS_RAW
GROUP BY event_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count desc;
-- counts the number of duplicates by the event_id
-- try changing the data so that ALL the duplicates are not 2 (have a varying number of duplicates)

SELECT quality, COUNT(*) AS row_count
FROM RAW.SENSOR_EVENTS_RAW
GROUP BY quality;
-- counts how many are GOOD and how many are BAD

SELECT plc_payload, COUNT(*) AS row_count
FROM RAW.SENSOR_EVENTS_RAW
GROUP BY plc_payload
ORDER BY plc_payload;


-- CLEANED LAYER
CREATE OR REPLACE TABLE CLEANED.SENSOR_EVENTS_CLEANED(
    event_id STRING,
    machine_id STRING,
    event_ts TIMESTAMP_NTZ,
    temperature FLOAT,
    pressure FLOAT,
    vibration FLOAT,
    cycle_time FLOAT,
    parts_per_hour FLOAT,
    machine_status STRING,
    sensor_quality NUMBER,
    plc_payload STRING,

    emergency_stop BOOLEAN,
    motor_overheating_warning BOOLEAN,
    hydraulic_pressure_valve_open BOOLEAN,

    quality STRING,
    actual_failure BOOLEAN,

    was_temperature_imputed BOOLEAN,
    cleaned_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);


CREATE OR REPLACE TABLE METADATA.STREAM_CONSUMPTION_LOG(
    event_id STRING,
    consumed_at TIMESTAMP_NTZ
);


CREATE OR REPLACE PROCEDURE METADATA.SP_REFRESH_CLEANED()
RETURNS STRING
LANGUAGE SQL
AS
$$

DECLARE

    v_run_id     STRING DEFAULT UUID_STRING();
    v_started    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
    v_rows       INTEGER DEFAULT 0;

BEGIN

    -- ---------------------------------------
    -- Log pipeline start
    -- ---------------------------------------

    INSERT INTO METADATA.INGESTION_LOG
        (
            run_id,
            pipeline_name,
            source_file,
            status,
            started_at
        )

    VALUES
        (
            :v_run_id,
            'SP_REFRESH_CLEANED',
            'RAW.SENSOR_EVENTS_RAW',
            'RUNNING',
            :v_started
        );


    -- ---------------------------------------
    -- Rebuild CLEANED layer
    -- ---------------------------------------

    TRUNCATE TABLE CLEANED.SENSOR_EVENTS_CLEANED;


    INSERT INTO CLEANED.SENSOR_EVENTS_CLEANED(
        event_id,
        machine_id,
        event_ts,
        temperature,
        pressure,
        vibration,
        cycle_time,
        parts_per_hour,
        machine_status,
        sensor_quality,
        plc_payload,
        emergency_stop,
        motor_overheating_warning,
        hydraulic_pressure_valve_open,
        quality,
        actual_failure,
        was_temperature_imputed
    )

    WITH deduped AS (

        SELECT *

        FROM RAW.SENSOR_EVENTS_RAW

        QUALIFY ROW_NUMBER() OVER(
            PARTITION BY event_id
            ORDER BY loaded_at DESC
        ) = 1

    ),

    with_imputation AS (

        SELECT

            event_id,
            machine_id,
            event_ts,

            COALESCE(
                temperature,

                AVG(temperature) OVER(
                    PARTITION BY machine_id
                    ORDER BY event_ts
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                )

            ) AS temperature,

            pressure,
            vibration,
            cycle_time,
            parts_per_hour,
            machine_status,
            sensor_quality,
            plc_payload,
            quality,
            actual_failure,

            CASE
                WHEN temperature IS NULL
                THEN TRUE
                ELSE FALSE
            END AS was_temperature_imputed

        FROM deduped
    )

    SELECT

        event_id,
        machine_id,
        event_ts,
        temperature,
        pressure,
        vibration,
        cycle_time,
        parts_per_hour,
        machine_status,
        sensor_quality,
        plc_payload,

        BITAND(
            COALESCE(
                TRY_TO_NUMBER(
                    REPLACE(plc_payload, '0x', ''),
                    'XX'
                ),
                0
            ),
            1
        ) > 0 AS emergency_stop,

        BITAND(
            COALESCE(
                TRY_TO_NUMBER(
                    REPLACE(plc_payload, '0x', ''),
                    'XX'
                ),
                0
            ),
            2
        ) > 0 AS motor_overheating_warning,

        BITAND(
            COALESCE(
                TRY_TO_NUMBER(
                    REPLACE(plc_payload, '0x', ''),
                    'XX'
                ),
                0
            ),
            4
        ) > 0 AS hydraulic_pressure_valve_open,

        quality,
        actual_failure,
        was_temperature_imputed

    FROM with_imputation;


    INSERT INTO METADATA.STREAM_CONSUMPTION_LOG
        (
            event_id,
            consumed_at
        )

    SELECT
        event_id,
        CURRENT_TIMESTAMP()

    FROM RAW.SENSOR_EVENTS_STREAM;

    v_rows := SQLROWCOUNT;


    -- ---------------------------------------
    -- Log success
    -- ---------------------------------------

    UPDATE METADATA.INGESTION_LOG

    SET
        status = 'SUCCESS',
        ended_at = CURRENT_TIMESTAMP(),
        rows_loaded = :v_rows

    WHERE run_id = :v_run_id;


    RETURN 'OK: ' || v_rows || ' rows loaded into CLEANED';


EXCEPTION

    WHEN OTHER THEN

        UPDATE METADATA.INGESTION_LOG

        SET
            status = 'FAILED',
            ended_at = CURRENT_TIMESTAMP(),
            message = :SQLERRM

        WHERE run_id = :v_run_id;


        INSERT INTO METADATA.ERROR_LOG
            (
                error_id,
                run_id,
                source_file,
                error_type,
                error_message,
                error_ts
            )

        VALUES
            (
                UUID_STRING(),
                :v_run_id,
                'RAW.SENSOR_EVENTS_RAW',
                'SP_REFRESH_CLEANED',
                :SQLERRM,
                CURRENT_TIMESTAMP()
            );


        RAISE;

END;

$$;

CREATE OR REPLACE PROCEDURE METADATA.SP_REFRESH_CURATED()
RETURNS STRING
LANGUAGE SQL
AS
$$

DECLARE

    v_run_id  STRING DEFAULT UUID_STRING();
    v_started TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();

BEGIN

    -- ---------------------------------------
    -- Log pipeline start
    -- ---------------------------------------

    INSERT INTO METADATA.INGESTION_LOG
        (
            run_id,
            pipeline_name,
            source_file,
            status,
            started_at
        )

    VALUES
        (
            :v_run_id,
            'SP_REFRESH_CURATED',
            'CLEANED.SENSOR_EVENTS_CLEANED',
            'RUNNING',
            :v_started
        );


    -- ======================================================
    -- MACHINE QUALITY SUMMARY
    -- ======================================================

    CREATE OR REPLACE TABLE CURATED.MACHINE_QUALITY_SUMMARY AS

    SELECT

        machine_id,

        COUNT(*) AS total_events,

        COUNT_IF(
            quality = 'BAD'
        ) AS bad_quality_events,

        COUNT_IF(
            actual_failure = TRUE
        ) AS actual_failures,

        ROUND(AVG(temperature), 2) AS avg_temperature,

        ROUND(AVG(pressure), 2) AS avg_pressure,

        ROUND(AVG(vibration), 3) AS avg_vibration,

        ROUND(AVG(cycle_time), 3) AS avg_cycle_time,

        ROUND(AVG(parts_per_hour), 1) AS avg_parts_per_hour,

        COUNT_IF(
            emergency_stop = TRUE
        ) AS emergency_stop_events,

        COUNT_IF(
            motor_overheating_warning = TRUE
        ) AS motor_overheat_events,

        COUNT_IF(
            hydraulic_pressure_valve_open = TRUE
        ) AS hydraulic_valve_open_events

    FROM CLEANED.SENSOR_EVENTS_CLEANED

    GROUP BY machine_id;


    -- ======================================================
    -- LINE QUALITY DAILY
    -- ======================================================

    CREATE OR REPLACE TABLE CURATED.LINE_QUALITY_DAILY AS

    SELECT

        DATE_TRUNC('DAY', event_ts) AS production_date,

        machine_id,

        COUNT(*) AS total_events,

        COUNT_IF(
            quality = 'BAD'
        ) AS bad_quality_events,

        ROUND(
            COUNT_IF(quality = 'BAD')
            * 100.0
            / COUNT(*),
            2
        ) AS bad_quality_rate_pct,

        COUNT_IF(
            actual_failure = TRUE
        ) AS failure_events,

        ROUND(AVG(temperature), 2) AS avg_temperature,

        ROUND(AVG(pressure), 2) AS avg_pressure,

        ROUND(AVG(vibration), 3) AS avg_vibration,

        ROUND(AVG(cycle_time), 3) AS avg_cycle_time,

        ROUND(AVG(parts_per_hour), 1) AS avg_parts_per_hour,

        COUNT_IF(
            emergency_stop = TRUE
        ) AS emergency_stop_events,

        COUNT_IF(
            motor_overheating_warning = TRUE
        ) AS motor_overheat_events,

        COUNT_IF(
            hydraulic_pressure_valve_open = TRUE
        ) AS hydraulic_valve_open_events

    FROM CLEANED.SENSOR_EVENTS_CLEANED

    GROUP BY
        DATE_TRUNC('DAY', event_ts),
        machine_id;


    -- ======================================================
    -- ML FEATURE TABLE
    -- ======================================================

    CREATE OR REPLACE TABLE CURATED.ML_ANOMALY_FEATURES AS

    SELECT

        event_id,
        machine_id,
        event_ts,

        temperature,
        pressure,
        vibration,
        cycle_time,
        parts_per_hour,
        sensor_quality,

        IFF(
            emergency_stop,
            1,
            0
        ) AS emergency_stop_flag,

        IFF(
            motor_overheating_warning,
            1,
            0
        ) AS motor_overheat_flag,

        IFF(
            hydraulic_pressure_valve_open,
            1,
            0
        ) AS hydraulic_valve_open_flag,

        IFF(
            actual_failure,
            1,
            0
        ) AS actual_failure_flag,

        IFF(
            quality = 'BAD',
            1,
            0
        ) AS bad_quality_flag

    FROM CLEANED.SENSOR_EVENTS_CLEANED

    WHERE temperature IS NOT NULL
      AND pressure IS NOT NULL
      AND vibration IS NOT NULL
      AND cycle_time IS NOT NULL
      AND parts_per_hour IS NOT NULL;


    -- ---------------------------------------
    -- Log success
    -- ---------------------------------------

    UPDATE METADATA.INGESTION_LOG

    SET
        status = 'SUCCESS',
        ended_at = CURRENT_TIMESTAMP()

    WHERE run_id = :v_run_id;


    RETURN 'OK: CURATED layer refreshed';


EXCEPTION

    WHEN OTHER THEN

        UPDATE METADATA.INGESTION_LOG

        SET
            status = 'FAILED',
            ended_at = CURRENT_TIMESTAMP(),
            message = :SQLERRM

        WHERE run_id = :v_run_id;


        INSERT INTO METADATA.ERROR_LOG
            (
                error_id,
                run_id,
                source_file,
                error_type,
                error_message,
                error_ts
            )

        VALUES
            (
                UUID_STRING(),
                :v_run_id,
                'CLEANED.SENSOR_EVENTS_CLEANED',
                'SP_REFRESH_CURATED',
                :SQLERRM,
                CURRENT_TIMESTAMP()
            );


        RAISE;

END;
$$;


CALL METADATA.SP_REFRESH_CLEANED();

CALL METADATA.SP_REFRESH_CURATED();


SELECT *
FROM CURATED.MACHINE_QUALITY_SUMMARY
ORDER BY bad_quality_events DESC
LIMIT 20;

SELECT *
FROM CURATED.LINE_QUALITY_DAILY
ORDER BY production_date, machine_id;

SELECT *
FROM CURATED.ML_ANOMALY_FEATURES;



-- ==========================================================
-- TASK 1: REFRESH CLEANED
-- ==========================================================

CREATE OR REPLACE TASK METADATA.TASK_REFRESH_CLEANED

    WAREHOUSE = IOT_TASK_WH

    SCHEDULE = '60 MINUTE'

    WHEN SYSTEM$STREAM_HAS_DATA(
        'RAW.SENSOR_EVENTS_STREAM'
    )

AS

    CALL METADATA.SP_REFRESH_CLEANED();


-- ==========================================================
-- TASK 2: REFRESH CURATED
-- ==========================================================

CREATE OR REPLACE TASK METADATA.TASK_REFRESH_CURATED

    WAREHOUSE = IOT_TASK_WH

    AFTER METADATA.TASK_REFRESH_CLEANED

AS

    CALL METADATA.SP_REFRESH_CURATED();


SELECT COUNT(*) AS cleaned_row_count
FROM CLEANED.SENSOR_EVENTS_CLEANED;


SELECT
    (SELECT COUNT(*) FROM RAW.SENSOR_EVENTS_RAW) AS raw_rows,
    (SELECT COUNT(*) FROM CLEANED.SENSOR_EVENTS_CLEANED) AS cleaned_rows;
    -- number of rows from each table

SELECT COUNT(*) AS remaining_missing_temperatures
FROM CLEANED.SENSOR_EVENTS_CLEANED
WHERE temperature IS NULL;
-- the number of rows from the new, cleaned table where the temperature is NULL


SELECT COUNT(*) AS row_count FROM CLEANED.SENSOR_EVENTS_CLEANED WHERE was_temperature_imputed = TRUE;

SELECT
    plc_payload,
    emergency_stop,
    motor_overheating_warning,
    hydraulic_pressure_valve_open,
    COUNT(*) AS row_count
FROM CLEANED.SENSOR_EVENTS_CLEANED
GROUP BY
    plc_payload,
    emergency_stop,
    motor_overheating_warning,
    hydraulic_pressure_valve_open
ORDER BY plc_payload;



SELECT *
FROM CURATED.MACHINE_QUALITY_SUMMARY
ORDER BY bad_quality_events DESC LIMIT 20;
-- number of bad quality events, # of emergency stop events, # of motor overheating events, and # of hydraulic valve open events are all 0

SELECT COUNT(*) AS machine_summary_row_count FROM CURATED.MACHINE_QUALITY_SUMMARY;


SHOW SCHEMAS;


SHOW TABLES IN SCHEMA RAW;
SHOW TABLES IN SCHEMA CLEANED;
SHOW TABLES IN SCHEMA CURATED;
SHOW TABLES IN SCHEMA METADATA;
SHOW PIPES IN SCHEMA RAW;




SELECT * FROM CURATED.LINE_QUALITY_DAILY
ORDER BY production_date, machine_id;


CREATE OR REPLACE VIEW CURATED.SENSOR_EVENTS_DASHBOARD AS
SELECT
    event_id,
    machine_id,
    event_ts,
    DATE_TRUNC('DAY', event_ts) AS production_date,
    temperature,
    pressure,
    vibration,
    cycle_time,
    parts_per_hour,
    machine_status,
    sensor_quality,
    plc_payload,
    emergency_stop,
    motor_overheating_warning,
    hydraulic_pressure_valve_open,
    quality,
    actual_failure,
    was_temperature_imputed,
    cleaned_at
FROM CLEANED.SENSOR_EVENTS_CLEANED;

SELECT * FROM CURATED.SENSOR_EVENTS_DASHBOARD;

SELECT
    COUNT(*) AS total_events,
    COUNT_IF(quality = 'BAD') AS bad_quality_events,
    ROUND(COUNT_IF(quality = 'BAD') * 100.0 / COUNT(*), 2) AS bad_quality_rate_pct,
    COUNT_IF(actual_failure = TRUE) AS failure_events,
    COUNT_IF(emergency_stop = TRUE) AS emergency_stop_events,
    COUNT_IF(motor_overheating_warning = TRUE) AS motor_overheat_events
FROM CURATED.SENSOR_EVENTS_DASHBOARD;



SELECT COUNT(*) FROM CURATED.ML_ANOMALY_FEATURES

SELECT * FROM CURATED.ML_ANOMALY_FEATURES;

SELECT COUNT(*) AS ml_feature_rows FROM CURATED.ML_ANOMALY_FEATURES;



-- Check task status/history

SELECT *
FROM TABLE(
    INFORMATION_SCHEMA.TASK_HISTORY(
        SCHEDULED_TIME_RANGE_START =>
            DATEADD(
                'hour',
                -24,
                CURRENT_TIMESTAMP()
            )
    )
)
ORDER BY SCHEDULED_TIME DESC;


-- Check pipeline logs

SELECT *
FROM METADATA.INGESTION_LOG
ORDER BY started_at DESC;


-- Check errors

SELECT *
FROM METADATA.ERROR_LOG
ORDER BY error_ts DESC;

ALTER TASK METADATA.TASK_REFRESH_CURATED RESUME;

ALTER TASK METADATA.TASK_REFRESH_CLEANED RESUME;