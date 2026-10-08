import os
import logging
import re
import subprocess
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
CRON_MARKER = "# gate-qris-managed-shutdown"
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
    error_message = None
    try:
        logger.info("[raspi] Relay ON")
        relay.on()
        time.sleep(RELAY_PULSE_SECONDS)
        success = True
    except Exception as exc:
        error_message = str(exc)
        logger.exception("[raspi] Relay error: %s", exc)
    finally:
        relay.off()
        logger.info("[raspi] Relay OFF")

    sio.emit(
        "gate:ack",
        {
            "commandId": payload.get("commandId"),
            "transactionId": payload.get("transactionId", "unknown"),
            "deviceCode": DEVICE_CODE,
            "success": success,
            "error": error_message,
        },
        namespace="/realtime",
    )


def set_shutdown_schedule(schedule_time):
    if schedule_time is not None and not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", schedule_time
    ):
        raise ValueError("time must be HH:MM or null to disable")

    current = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    if current.returncode != 0 and "no crontab for" not in current.stderr.lower():
        raise RuntimeError(current.stderr.strip() or "Unable to read crontab")

    lines = current.stdout.splitlines() if current.returncode == 0 else []
    lines = [line for line in lines if line.strip() != CRON_MARKER]
    lines = [
        line
        for line in lines
        if not (
            len(line.split(maxsplit=5)) == 6
            and line.split(maxsplit=5)[5] == "/sbin/shutdown -h now"
        )
    ]

    if schedule_time is not None:
        hour, minute = schedule_time.split(":")
        lines.extend(
            [
                CRON_MARKER,
                f"{int(minute)} {int(hour)} * * * sudo -n /sbin/shutdown -h now",
            ]
        )

    updated = subprocess.run(
        ["crontab", "-"], input="\n".join(lines) + "\n", text=True,
        capture_output=True, check=False
    )
    if updated.returncode != 0:
        raise RuntimeError(updated.stderr.strip() or "Unable to update crontab")


def get_shutdown_schedule():
    current = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    if current.returncode != 0:
        if "no crontab for" in current.stderr.lower():
            return None
        raise RuntimeError(current.stderr.strip() or "Unable to read crontab")

    lines = current.stdout.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.strip() != CRON_MARKER:
            continue
        match = re.fullmatch(
            r"(\d{1,2}) (\d{1,2}) \* \* \* sudo -n /sbin/shutdown -h now",
            lines[index + 1].strip(),
        )
        if not match:
            raise RuntimeError("Managed shutdown schedule entry is invalid")
        minute, hour = (int(value) for value in match.groups())
        if minute > 59 or hour > 23:
            raise RuntimeError("Managed shutdown schedule entry is invalid")
        return f"{hour:02d}:{minute:02d}"
    return None


@sio.on("system:command", namespace="/realtime")
def handle_system_command(payload):
    logger.info("[raspi] System command received: %s", payload)
    action = payload.get("action")
    success = False
    error_message = None

    try:
        if action == "shutdown":
            subprocess.run(
                ["sudo", "-n", "/sbin/shutdown", "-h", "now"],
                check=True,
                timeout=10,
            )
        elif action == "reboot":
            subprocess.run(
                ["sudo", "-n", "/sbin/reboot"], check=True, timeout=10
            )
        elif action == "set-shutdown-schedule":
            set_shutdown_schedule(payload.get("time"))
        elif action == "get-shutdown-schedule":
            success = True
            schedule_time = get_shutdown_schedule()
        else:
            raise ValueError("Unsupported system command")
        if action != "get-shutdown-schedule":
            success = True
    except Exception as exc:
        error_message = str(exc)
        logger.exception("[raspi] System command failed: %s", exc)

    acknowledgement = {
        "commandId": payload.get("commandId"),
        "deviceCode": DEVICE_CODE,
        "action": action,
        "success": success,
        "error": error_message,
    }
    if action == "get-shutdown-schedule":
        acknowledgement["time"] = schedule_time if success else None

    sio.emit(
        "system:ack",
        acknowledgement,
        namespace="/realtime",
    )
    if action == "get-shutdown-schedule":
        return acknowledgement


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
