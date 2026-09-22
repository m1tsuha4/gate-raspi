# Gate QRIS Raspberry Pi Client

This client connects a Raspberry Pi to the Gate QRIS server through Socket.IO. When the server sends a `gate:open` event, the client activates the relay on GPIO pin 4 for 0.5 seconds, then sends a `gate:ack` response.

The relay uses the same configuration as the working manual test:

- GPIO pin: BCM 4
- Active level: LOW (`active_high=False`)
- Pulse duration: 0.5 seconds
- Relay state at startup and shutdown: OFF

## Hardware

Use the Raspberry Pi **BCM GPIO numbering**. Connect the relay input/control pin to GPIO 4, with the relay power and ground connected according to the relay module requirements.

> Do not connect a relay coil directly to a Raspberry Pi GPIO pin. Use a suitable relay module or driver circuit, and verify the module's voltage and current requirements.

## Requirements

- Raspberry Pi with Raspberry Pi OS
- Python 3
- Network access to the Gate QRIS API
- A relay module connected to BCM GPIO 4
- A registered gate device with a matching device code and device token

The Python dependencies include the Socket.IO WebSocket client and the `lgpio`
GPIO backend. The WebSocket client is required because `gate_client.py` uses
the WebSocket transport directly.

## Installation

Open a terminal on the Raspberry Pi and enter the client directory:

```bash
cd ~/gate-qris/test-raspi
```

Create and activate a virtual environment:

```bash
sudo apt update
sudo apt install -y python3-venv swig build-essential python3-dev liblgpio-dev
python3 -m venv .venv
source .venv/bin/activate
```

Install the Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The virtual environment must be activated whenever you run the client manually. The `systemd` setup below uses the virtual environment directly, so activation is not needed for automatic startup.

If `pip install -r requirements.txt` was already attempted and failed, install
the native `lgpio` development library first, then retry:

```bash
sudo apt update
sudo apt install -y liblgpio-dev
source .venv/bin/activate
python -m pip install --upgrade -r requirements.txt
```

## Configuration

The client has defaults, but set the server URL, device code, and device token for the actual Raspberry Pi:

```bash
export GATE_SERVER_URL="http://192.168.1.100:3000"
export GATE_DEVICE_CODE="GATE-001"
export GATE_DEVICE_TOKEN="your-device-token"
export GATE_RELAY_PIN="4"
export GATE_RELAY_PULSE_SECONDS="0.5"
```

Replace `192.168.1.100` with the IP address or hostname of the Gate QRIS server. The server URL should not include `/realtime`; the client adds that Socket.IO namespace itself.

For a quick local setup, you can create a `.env`-style shell file:

```bash
nano .env
```

Add:

```bash
export GATE_SERVER_URL="http://192.168.1.100:3000"
export GATE_DEVICE_CODE="GATE-001"
export GATE_DEVICE_TOKEN="your-device-token"
export GATE_RELAY_PIN="4"
export GATE_RELAY_PULSE_SECONDS="0.5"
```

Load it before starting the client:

```bash
source .env
```

Keep this file private because it contains the device token.

## Run manually

From `test-raspi`:

```bash
source .venv/bin/activate
source .env
python gate_client.py
```

A successful connection prints a message similar to:

```text
[raspi] Connected to http://192.168.1.100:3000/realtime
```

The client sends a heartbeat every five seconds. To test the relay, trigger a gate opening from the Gate QRIS server. The client should print:

```text
[raspi] Open gate command received: ...
[raspi] Relay ON
[raspi] Relay OFF
```

Stop a manual run with `Ctrl+C`.

## Start automatically on boot

`systemd` is recommended because it starts the client after boot, restarts it if it exits, and records logs in the system journal.

### 1. Choose the installation path

This README assumes the project is installed at:

```text
/home/pi/gate-qris/test-raspi
```

If the project is in another directory, replace that path in the commands and service file below. Check the current user and path with:

```bash
whoami
pwd
```

### 2. Create the service environment file

Create a root-readable environment file:

```bash
sudo nano /etc/gate-client.env
```

Add the following and replace the values:

```text
GATE_SERVER_URL=http://192.168.1.100:3000
GATE_DEVICE_CODE=GATE-001
GATE_DEVICE_TOKEN=your-device-token
GATE_RELAY_PIN=4
GATE_RELAY_PULSE_SECONDS=0.5
```

Protect the token file:

```bash
sudo chmod 600 /etc/gate-client.env
```

### 3. Create the `systemd` service

Create the unit file:

```bash
sudo nano /etc/systemd/system/gate-client.service
```

Paste this configuration. Change `User` and the paths if your Raspberry Pi user or project directory is different:

```ini
[Unit]
Description=Gate QRIS Raspberry Pi Client
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/gate-qris/test-raspi
EnvironmentFile=/etc/gate-client.env
ExecStart=/home/pi/gate-qris/test-raspi/.venv/bin/python /home/pi/gate-qris/test-raspi/gate_client.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 4. Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gate-client.service
```

Check its status:

```bash
sudo systemctl status gate-client.service
```

View live logs:

```bash
sudo journalctl -u gate-client.service -f
```

The service should show the connection message and heartbeat messages. Trigger a gate opening from the server to test the relay.

## Service management

Stop the client:

```bash
sudo systemctl stop gate-client.service
```

Start it again:

```bash
sudo systemctl start gate-client.service
```

Restart it after changing the environment file or Python code:

```bash
sudo systemctl restart gate-client.service
```

Disable automatic startup:

```bash
sudo systemctl disable --now gate-client.service
```

After changing the service unit itself, reload `systemd` before restarting:

```bash
sudo systemctl daemon-reload
sudo systemctl restart gate-client.service
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'gpiozero'`

Activate the virtual environment and install the requirements again:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### `websocket-client package not installed`

The client is configured to use WebSocket transport. Reinstall the requirements
inside the active virtual environment:

```bash
source .venv/bin/activate
python -m pip install --upgrade -r requirements.txt
```

You can verify the package is installed with:

```bash
python -c "import websocket; print(websocket.__version__)"
```

### GPIO backend fallback warnings

Warnings about falling back from `lgpio`, `RPi.GPIO`, or `pigpio` mean that
`gpiozero` could not load a native GPIO backend. Install the requirements inside
the Raspberry Pi virtual environment:

```bash
source .venv/bin/activate
python -m pip install --upgrade lgpio gpiozero
```

The fallback warning is separate from the Socket.IO connection error. Check
that `lgpio` imports successfully:

```bash
python -c "import lgpio; print('lgpio OK')"
```

### The client cannot connect

Check that the server URL is reachable from the Raspberry Pi and that the Socket.IO server is running. Confirm that the device code and device token are registered and match the values in `/etc/gate-client.env`.

### The relay does not activate

Confirm that the relay is connected to BCM GPIO 4, that the relay module has the required power and ground, and that the relay is active-low. You can try a different pin without changing the code by setting `GATE_RELAY_PIN` in the environment file.

### The service starts but immediately stops

Read the full service log:

```bash
sudo journalctl -u gate-client.service -n 100 --no-pager
```

Also verify that the paths in `WorkingDirectory` and `ExecStart` exist and that the `User` has permission to access the project and GPIO hardware.
