import json
import logging
import os
import signal
import ssl
import sys
import time
from pathlib import Path

import numpy as np
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from scipy.integrate import solve_ivp

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_EDGE_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_EDGE_PASSWORD")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "plant/reactor/telemetry")
SENSOR_ID = os.getenv("SENSOR_ID", "CSTR_01")
CA_CERT = os.getenv("MQTT_CA_CERT", str(Path(__file__).resolve().parents[1] / "certs" / "ca.crt"))
PUBLISH_INTERVAL = float(os.getenv("PUBLISH_INTERVAL", "1.0"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("iiot-edge")

if not MQTT_USERNAME or not MQTT_PASSWORD:
    raise RuntimeError("MQTT_EDGE_USERNAME and MQTT_EDGE_PASSWORD must be set.")
if not os.path.isfile(CA_CERT):
    raise FileNotFoundError(f"MQTT CA certificate not found: {CA_CERT}")

V, F = 100.0, 10.0
Ca0, T0 = 1.0, 300.0
k0, E_R = 1e10, 8000.0

def cstr_ode(t, y):
    Ca, T = y
    k = k0 * np.exp(-E_R / T)
    return [
        (F / V) * (Ca0 - Ca) - k * Ca,
        (F / V) * (T0 - T) + 130.0 * k * Ca - 1.5 * (T - 298.0),
    ]

client = mqtt.Client(CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.reconnect_delay_set(min_delay=1, max_delay=30)
client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
client.tls_insecure_set(False)

running = True

def stop_handler(signum, frame):
    global running
    running = False

signal.signal(signal.SIGINT, stop_handler)
signal.signal(signal.SIGTERM, stop_handler)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        logger.error("MQTT connection failed: %s", reason_code)
    else:
        logger.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    logger.warning("MQTT disconnected: %s", reason_code)

client.on_connect = on_connect
client.on_disconnect = on_disconnect

def main():
    global running
    logger.info("Starting CSTR digital twin...")
    y_current = np.array([0.5, 310.0], dtype=float)
    t_current = 0.0
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    try:
        while running:
            sol = solve_ivp(cstr_ode, [t_current, t_current + PUBLISH_INTERVAL], y_current)
            if not sol.success:
                raise RuntimeError(f"CSTR ODE solver failed: {sol.message}")
            y_current = sol.y[:, -1]
            t_current += PUBLISH_INTERVAL
            ca_noisy = y_current[0] + np.random.normal(0, 0.005)
            temp_noisy = y_current[1] + np.random.normal(0, 0.4)
            payload = {
                "timestamp": time.time(),
                "sensor_id": SENSOR_ID,
                "concentration_mol_L": round(float(ca_noisy), 4),
                "temperature_K": round(float(temp_noisy), 2),
            }
            if not client.is_connected():
                logger.warning("MQTT broker unavailable; skipping telemetry publish.")
            else:
                try:
                    info = client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
                    info.wait_for_publish(timeout=5)

                    if not info.is_published():
                        logger.warning("MQTT publish acknowledgement was not received.")
                except (RuntimeError, ValueError) as exc:
                    logger.warning("MQTT publish failed; will retry on the next cycle: %s", exc)

            time.sleep(PUBLISH_INTERVAL)
    finally:
        logger.info("Stopping digital twin...")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
