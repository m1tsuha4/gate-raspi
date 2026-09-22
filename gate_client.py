import os
import time
import socketio
from gpiozero import OutputDevice

SERVER_URL = os.getenv("GATE_SERVER_URL", "http://localhost:3000")
DEVICE_CODE = os.getenv("GATE_DEVICE_CODE", "GATE-001")
DEVICE_TOKEN = os.getenv("GATE_DEVICE_TOKEN", "replace-with-device-token")
RELAY_PIN = int(os.getenv("GATE_RELAY_PIN", "4"))
RELAY_PULSE_SECONDS = float(os.getenv("GATE_RELAY_PULSE_SECONDS", "0.5"))

sio = socketio.Client(reconnection=True)
relay = OutputDevice(RELAY_PIN, active_high=False, initial_value=False)


@sio.event(namespace="/realtime")
def connect():
    print(f"[raspi] Connected to {SERVER_URL}/realtime")
    sio.emit("gate:heartbeat", {"deviceCode": DEVICE_CODE}, namespace="/realtime")


@sio.event(namespace="/realtime")
def connect_error(data):
    print(f"[raspi] Connection error: {data}")


@sio.event(namespace="/realtime")
def disconnect():
    print("[raspi] Disconnected from server")


@sio.on("gate:open", namespace="/realtime")
def handle_gate_open(payload):
    print(f"[raspi] Open gate command received: {payload}")

    success = False
    try:
        print("[raspi] Relay ON")
        relay.on()
        time.sleep(RELAY_PULSE_SECONDS)
        success = True
    except Exception as exc:
        print(f"[raspi] Relay error: {exc}")
    finally:
        relay.off()
        print("[raspi] Relay OFF")

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
            print("[raspi] Heartbeat sent")


if __name__ == "__main__":
    print("[raspi] Starting gate client...")
    print(f"[raspi] Server: {SERVER_URL}/realtime")
    print(f"[raspi] Device code: {DEVICE_CODE}")
    print(f"[raspi] Device token configured: {DEVICE_TOKEN != 'replace-with-device-token'}")
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
        print("[raspi] Stopped")
        relay.off()
        relay.close()
        sio.disconnect()
