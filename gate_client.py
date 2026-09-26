import os
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import time
import socketio
from gpiozero import OutputDevice

SERVER_URL = os.getenv("GATE_SERVER_URL", "http://localhost:3000")
DEVICE_CODE = os.getenv("GATE_DEVICE_CODE", "GATE-001")
DEVICE_TOKEN = os.getenv("GATE_DEVICE_TOKEN", "replace-with-device-token")
RELAY_PIN = int(os.getenv("GATE_RELAY_PIN", "4"))
RELAY_PULSE_SECONDS = float(os.getenv("GATE_RELAY_PULSE_SECONDS", "0.5"))
LOG_DIR = Path(
    os.getenv("GATE_LOG_DIR", str(Path(__file__).resolve().parent / "logs"))
)
LOG_DIR.mkdir(parents=True, exist_ok=True)

formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler = TimedRotatingFileHandler(
    LOG_DIR / "gate-client.log",
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
file_handler.setFormatter(formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger = logging.getLogger("gate_client")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

sio = socketio.Client(reconnection=True)
relay = OutputDevice(RELAY_PIN, active_high=False, initial_value=False)


@sio.event(namespace="/realtime")
def connect():
    logger.info("[raspi] Connected to %s/realtime", SERVER_URL)
    sio.emit("gate:heartbeat", {"deviceCode": DEVICE_CODE}, namespace="/realtime")


@sio.event(namespace="/realtime")
def connect_error(data):
    logger.error("[raspi] Connection error: %s", data)


@sio.event(namespace="/realtime")
def disconnect():
    logger.warning("[raspi] Disconnected from server")


@sio.on("gate:open", namespace="/realtime")
def handle_gate_open(payload):
    logger.info("[raspi] Open gate command received: %s", payload)

    success = False
    try:
        logger.info("[raspi] Relay ON")
        relay.on()
        time.sleep(RELAY_PULSE_SECONDS)
        success = True
    except Exception as exc:
        logger.exception("[raspi] Relay error: %s", exc)
    finally:
        relay.off()
        logger.info("[raspi] Relay OFF")

    sio.emit(
        "gate:ack",
        {
            "transactionId": payload.get("transactionId", "unknown"),
            "deviceCode": DEVICE_CODE,
            "success": success,
        },
        namespace="/realtime",
    )


def send_heartbeat_loop():
    while True:
        time.sleep(5)
        if sio.connected:
            sio.emit("gate:heartbeat", {"deviceCode": DEVICE_CODE}, namespace="/realtime")
            logger.debug("[raspi] Heartbeat sent")


if __name__ == "__main__":
    logger.info("[raspi] Starting gate client")
    logger.info("[raspi] Server: %s/realtime", SERVER_URL)
    logger.info("[raspi] Device code: %s", DEVICE_CODE)
    logger.info(
        "[raspi] Device token configured: %s",
        DEVICE_TOKEN != "replace-with-device-token",
    )
    sio.connect(
        SERVER_URL,
        namespaces=["/realtime"],
        auth={
            "deviceCode": DEVICE_CODE,
            "deviceToken": DEVICE_TOKEN,
        },
        transports=["websocket"],
    )

    try:
        send_heartbeat_loop()
    except KeyboardInterrupt:
        logger.info("[raspi] Stopped")
        relay.off()
        relay.close()
        sio.disconnect()
