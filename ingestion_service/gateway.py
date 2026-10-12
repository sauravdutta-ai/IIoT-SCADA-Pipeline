import collections
import logging
import os
import ssl
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Deque, List

import numpy as np
import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from pydantic import BaseModel, Field
from sklearn.ensemble import IsolationForest
from paho.mqtt.enums import CallbackAPIVersion


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("iiot-gateway")


MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_GATEWAY_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_GATEWAY_PASSWORD")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "plant/reactor/telemetry")
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "../certs/ca.crt")

INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = os.getenv("INFLUX_ORG", "my-org")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "iiot_data")

# InfluxDB write retry configuration
INFLUX_WRITE_MAX_RETRIES = int(
    os.getenv("INFLUX_WRITE_MAX_RETRIES", "3")
)
INFLUX_WRITE_RETRY_DELAY_SECONDS = float(
    os.getenv("INFLUX_WRITE_RETRY_DELAY_SECONDS", "0.5")
)

BUFFER_SIZE = int(os.getenv("ML_BUFFER_SIZE", "200"))
RETRAIN_INTERVAL_SECONDS = int(os.getenv("ML_RETRAIN_INTERVAL_SECONDS", "300"))
WARMUP_TEMPERATURE_THRESHOLD_K = float(
    os.getenv("WARMUP_TEMPERATURE_THRESHOLD_K", "325.0")
)

# Configurable Isolation Forest parameters
ML_CONTAMINATION = float(os.getenv("ML_CONTAMINATION", "0.05"))
ML_N_ESTIMATORS = int(os.getenv("ML_N_ESTIMATORS", "200"))


if not MQTT_USERNAME or not MQTT_PASSWORD:
    raise RuntimeError(
        "MQTT_GATEWAY_USERNAME and MQTT_GATEWAY_PASSWORD must be set."
    )

if not INFLUX_TOKEN:
    raise RuntimeError("INFLUX_TOKEN must be set.")


class Telemetry(BaseModel):
    timestamp: float = Field(..., ge=0)
    sensor_id: str = Field(..., min_length=1, max_length=100)
    concentration_mol_L: float = Field(..., ge=0.0)
    temperature_K: float = Field(..., gt=0.0)


data_buffer: Deque[List[float]] = collections.deque(maxlen=BUFFER_SIZE)

state_lock = threading.Lock()
model_lock = threading.Lock()

ml_model = IsolationForest(
    contamination=ML_CONTAMINATION,
    random_state=42,
    n_estimators=ML_N_ESTIMATORS,
)

model_ready = False
last_retrain_monotonic = 0.0

mqtt_connected = False
influx_healthy = False

# Message processing counters
messages_received = 0
messages_written = 0
messages_failed = 0


db_client = InfluxDBClient(
    url=INFLUX_URL,
    token=INFLUX_TOKEN,
    org=INFLUX_ORG,
)

write_api = db_client.write_api(write_options=SYNCHRONOUS)

mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)


def find_ca_cert():
    for path in [
        MQTT_CA_CERT,
        os.path.join(os.path.dirname(__file__), "..", "certs", "ca.crt"),
        os.path.join(os.getcwd(), "certs", "ca.crt"),
    ]:
        path = os.path.abspath(path)
        if os.path.isfile(path):
            return path

    raise FileNotFoundError("MQTT CA certificate could not be found.")


def retrain_if_due():
    global model_ready, last_retrain_monotonic, ml_model

    now = time.monotonic()

    with state_lock:
        if len(data_buffer) < BUFFER_SIZE:
            return False

        if (
            model_ready
            and now - last_retrain_monotonic < RETRAIN_INTERVAL_SECONDS
        ):
            return False

        training_matrix = np.asarray(data_buffer, dtype=float)

    # Train a new model without modifying the active model.
    new_model = IsolationForest(
        contamination=ML_CONTAMINATION,
        random_state=42,
        n_estimators=ML_N_ESTIMATORS,
    )

    new_model.fit(training_matrix)

    # Atomically replace the active model.
    with model_lock:
        ml_model = new_model

    with state_lock:
        model_ready = True
        last_retrain_monotonic = now

    logger.info(
        "Isolation Forest trained on %d samples.",
        len(training_matrix),
    )

    return True


def write_point_with_retry(point: Point) -> bool:
    """
    Write a telemetry point to InfluxDB with bounded exponential backoff.

    The initial write is attempted immediately. If it fails, the function
    retries up to INFLUX_WRITE_MAX_RETRIES additional times.

    With the default configuration:
        attempt 1 -> immediate
        attempt 2 -> after 0.5 seconds
        attempt 3 -> after 1.0 second
        attempt 4 -> after 2.0 seconds

    Returns True when the write succeeds and False when all attempts fail.
    """

    for attempt in range(INFLUX_WRITE_MAX_RETRIES + 1):
        try:
            write_api.write(
                bucket=INFLUX_BUCKET,
                org=INFLUX_ORG,
                record=point,
            )

            return True

        except Exception as exc:
            if attempt >= INFLUX_WRITE_MAX_RETRIES:
                logger.error(
                    "InfluxDB write failed after %d retries: %s",
                    INFLUX_WRITE_MAX_RETRIES,
                    exc,
                )
                return False

            delay = INFLUX_WRITE_RETRY_DELAY_SECONDS * (2**attempt)

            logger.warning(
                "InfluxDB write failed (attempt %d/%d); "
                "retrying in %.2fs: %s",
                attempt + 1,
                INFLUX_WRITE_MAX_RETRIES + 1,
                delay,
                exc,
            )

            time.sleep(delay)

    return False


def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_connected

    if reason_code.is_failure:
        mqtt_connected = False
        logger.error("MQTT connection failed: %s", reason_code)
        return

    mqtt_connected = True
    client.subscribe(MQTT_TOPIC, qos=1)

    logger.info("Subscribed to %s", MQTT_TOPIC)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    global mqtt_connected

    mqtt_connected = False
    logger.warning("MQTT disconnected: %s", reason_code)


def on_message(client, userdata, msg):
    global influx_healthy
    global messages_received
    global messages_written
    global messages_failed

    with state_lock:
        messages_received += 1

    try:
        data = Telemetry.model_validate_json(msg.payload)

        current_vector = [
            data.temperature_K,
            data.concentration_mol_L,
        ]

        with state_lock:
            ready = model_ready

        # Predict before adding the current sample to the training buffer.
        # This preserves the existing no-current-sample-leakage behavior.
        if ready:
            with model_lock:
                prediction = ml_model.predict([current_vector])[0]
                anomaly_score = float(
                    ml_model.decision_function([current_vector])[0]
                )

            is_anomaly = bool(prediction == -1)
        else:
            is_anomaly = (
                data.temperature_K > WARMUP_TEMPERATURE_THRESHOLD_K
            )
            anomaly_score = None

        with state_lock:
            data_buffer.append(current_vector)

        retrain_if_due()

        point = (
            Point("reactor_metrics")
            .tag("sensor", data.sensor_id)
            .field("concentration", float(data.concentration_mol_L))
            .field("temperature", float(data.temperature_K))
            .field("anomaly_flag", bool(is_anomaly))
            .time(
                datetime.fromtimestamp(
                    data.timestamp,
                    tz=timezone.utc,
                )
            )
        )

        if anomaly_score is not None:
            point.field("anomaly_score", anomaly_score)

        if not write_point_with_retry(point):
            with state_lock:
                messages_failed += 1

            influx_healthy = False
            return

        with state_lock:
            messages_written += 1

        influx_healthy = True

    except Exception:
        with state_lock:
            messages_failed += 1

        influx_healthy = False

        logger.exception("Telemetry processing failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global influx_healthy

    ca_cert = find_ca_cert()

    mqtt_client.tls_set(
        ca_certs=ca_cert,
        tls_version=ssl.PROTOCOL_TLSv1_2,
    )

    mqtt_client.tls_insecure_set(False)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    try:
        influx_healthy = db_client.ping()

        if not influx_healthy:
            raise RuntimeError("InfluxDB health check failed.")

        mqtt_client.connect(
            MQTT_HOST,
            MQTT_PORT,
            60,
        )

        mqtt_client.loop_start()

        logger.info("IIoT gateway started.")

        yield

    finally:
        logger.info("Shutting down IIoT gateway...")

        mqtt_client.loop_stop()

        try:
            mqtt_client.disconnect()
        except Exception:
            logger.exception("Error disconnecting MQTT.")

        write_api.close()
        db_client.close()


app = FastAPI(
    title="IIoT Telemetry Gateway & SCADA API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """
    Liveness/diagnostic endpoint.

    The service itself is considered alive as long as this endpoint
    can respond. Dependency state and processing counters are included
    for observability.
    """

    with state_lock:
        buffer_fill = len(data_buffer)
        current_model_ready = model_ready
        received = messages_received
        written = messages_written
        failed = messages_failed

    return {
        "status": "ok",
        "mqtt_connected": mqtt_connected,
        "influx_healthy": influx_healthy,
        "buffer_size": buffer_fill,
        "buffer_capacity": BUFFER_SIZE,
        "model_ready": current_model_ready,
        "messages_received": received,
        "messages_written": written,
        "messages_failed": failed,
    }


@app.get("/ready")
def readiness_check(response: Response):
    """
    Readiness endpoint.

    The gateway is ready to receive/process telemetry only when
    both MQTT and InfluxDB are available.
    """

    ready = mqtt_connected and influx_healthy

    if not ready:
        response.status_code = 503

    return {
        "ready": ready,
        "mqtt_connected": mqtt_connected,
        "influx_healthy": influx_healthy,
    }


@app.get("/telemetry/latest")
def get_latest_telemetry():
    query = f'''
        from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -5m)
            |> filter(fn: (r) => r._measurement == "reactor_metrics")
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> sort(columns: ["_time"], desc: true)
            |> limit(n: 1)
    '''

    try:
        tables = db_client.query_api().query(
            query,
            org=INFLUX_ORG,
        )

    except Exception as exc:
        logger.exception("Failed to query latest telemetry.")

        raise HTTPException(
            status_code=503,
            detail="Telemetry database unavailable.",
        ) from exc

    for table in tables:
        for record in table.records:
            return {
                "time": record.get_time(),
                "sensor": record.values.get("sensor"),
                "temperature": record.values.get("temperature"),
                "concentration": record.values.get("concentration"),
                "anomaly_flag": record.values.get("anomaly_flag"),
                "anomaly_score": record.values.get("anomaly_score"),
            }

    raise HTTPException(
        status_code=404,
        detail="No recent telemetry found.",
    )


if __name__ == "__main__":
    uvicorn.run(
        "gateway:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )