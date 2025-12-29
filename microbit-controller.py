import asyncio
import os
import sys
import threading
import time
import requests
import shutil
import serial
import serial.tools.list_ports
from typing import Optional
from bleak import BleakScanner, BleakClient

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
VERSION_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/main/details.txt"
FIRMWARE_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/main/firmware.hex"
LOCAL_VERSION_FILE = "current_version.txt"
LOCAL_FIRMWARE = "firmware.hex"

UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"


# ---------------------------------------------------------
# VERSION CHECKING + FIRMWARE UPDATE
# ---------------------------------------------------------
def get_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE):
        return "0.0"
    return open(LOCAL_VERSION_FILE).read().strip()


def get_remote_version():
    try:
        r = requests.get(VERSION_URL, timeout=5)
        r.raise_for_status()
        return r.text.strip()
    except:
        return None


def download_firmware():
    print("Downloading firmware...")
    r = requests.get(FIRMWARE_URL, timeout=10)
    r.raise_for_status()
    with open(LOCAL_FIRMWARE, "wb") as f:
        f.write(r.content)
    print("Firmware downloaded.")
    return LOCAL_FIRMWARE


def find_microbit_drive():
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            try:
                if "MICROBIT" in os.listdir(drive):
                    return drive
            except:
                pass
    return None


def flash_firmware():
    drive = find_microbit_drive()
    if not drive:
        print("❌ MICROBIT drive not found. Plug it in and try again.")
        return False

    dest = os.path.join(drive, "firmware.hex")
    print(f"Copying firmware to {dest}...")
    shutil.copy(LOCAL_FIRMWARE, dest)
    print("Firmware copied. Micro:bit will reboot and flash.")
    return True


def perform_update(remote_version):
    fw = download_firmware()
    if flash_firmware():
        with open(LOCAL_VERSION_FILE, "w") as f:
            f.write(remote_version)
        print("Firmware updated successfully.")
        print("Restarting controller...")
        os.execv(sys.executable, ["python"] + sys.argv)


# ---------------------------------------------------------
# MICROBIT HYBRID CONTROLLER
# ---------------------------------------------------------
class Microbit:
    def __init__(self, mode="BOTH", dev_mode=False):
        self.dev_mode = dev_mode
        self.mode = mode.upper()
        self.current_mode = None
        self.ser: Optional[serial.Serial] = None
        self.ble_client: Optional[BleakClient] = None
        self.active_rx = RX_UUID

        print(f"--- 2025 micro:bit Hybrid Controller (Mode: {mode}) ---")

        # Start async loop
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

        # Check for firmware updates BEFORE connecting
        self._check_firmware_update()

        # Connect to micro:bit
        self.reconnect()

    # ---------------------------
    # Update Check
    # ---------------------------
    def _check_firmware_update(self):
        local = get_local_version()
        remote = get_remote_version()

        if not remote:
            print("⚠️  Could not check for firmware updates.")
            return

        if remote == local:
            print(f"Firmware OK (v{local})")
            return

        print(f"\n⚠️  Firmware update available!")
        print(f"   Installed: v{local}")
        print(f"   Latest:    v{remote}")

        choice = input("Update now? (y/n): ").strip().lower()
        if choice == "y":
            perform_update(remote)

    # ---------------------------
    # Async loop
    # ---------------------------
    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # ---------------------------
    # Connection Logic
    # ---------------------------
    def reconnect(self):
        # SERIAL
        if self.mode in ["BOTH", "SERIAL"]:
            for p in serial.tools.list_ports.comports():
                if any(x in p.description for x in ["micro:bit", "mbed", "USB Serial"]):
                    try:
                        self.ser = serial.Serial(p.device, 115200, timeout=1)
                        self.current_mode = "SERIAL"
                        self._start_serial_listener()
                        print(f"Status: Connected via USB ({p.device})")
                        return
                    except:
                        pass

        # BLE
        if self.mode in ["BOTH", "BLE"]:
            future = asyncio.run_coroutine_threadsafe(self._connect_ble(), self.loop)
            try:
                if future.result(timeout=35):
                    self.current_mode = "BLE"
                    print("Status: Connected via Bluetooth")
                    return
            except:
                pass

        print("Status: Connection failed.")

    async def _connect_ble(self):
        devices = await BleakScanner.discover(timeout=10.0)
        candidates = [d for d in devices if "micro:bit" in (d.name or "").lower()]

        if not candidates:
            return False

        target = candidates[0]
        self.ble_client = BleakClient(target)
        await self.ble_client.connect()

        try:
            await self.ble_client.start_notify(TX_UUID, self._on_data_received)
            self.active_rx = RX_UUID
            return True
        except:
            try:
                await self.ble_client.start_notify(RX_UUID, self._on_data_received)
                self.active_rx = TX_UUID
                return True
            except:
                return False

    # ---------------------------
    # Data Handling
    # ---------------------------
    def _on_data_received(self, handle, data):
        if isinstance(data, (bytes, bytearray)):
            msg = data.decode().strip()
        else:
            msg = str(data).strip()

        if msg:
            print(f"\n[MICROBIT]: {msg}\n> ", end="")

    def _start_serial_listener(self):
        def listen():
            while self.ser and self.ser.is_open:
                try:
                    line = self.ser.readline().decode().strip()
                    if line:
                        self._on_data_received(None, line)
                except:
                    break

        threading.Thread(target=listen, daemon=True).start()

    # ---------------------------
    # Commands
    # ---------------------------
    def send(self, cmd: str):
        msg = (cmd.strip() + "\n").encode()
        if self.current_mode == "SERIAL" and self.ser:
            self.ser.write(msg)
        elif self.current_mode == "BLE" and self.ble_client:
            asyncio.run_coroutine_threadsafe(
                self.ble_client.write_gatt_char(self.active_rx, msg, response=False),
                self.loop
            )

    # Convenience commands
    def get_sensor(self, s): self.send(f"get_sensor {s}")
    def get_pin(self, p): self.send(f"get_pin {p}")
    def tone(self, f, d): self.send(f"tone {f} {d}")
    def pin_write(self, t, p, v): self.send(f"pin {t} {p} {v}")
    def print_text(self, t): self.send(f"print {t}")
    def plot(self, x, y): self.send(f"plot {x} {y}")
    def unplot(self, x, y): self.send(f"unplot {x} {y}")
    def toggle(self, x, y): self.send(f"toggle {x} {y}")
    def clear(self): self.send("clear")
    def reset(self): self.send("reset")
    def ping(self): self.send("ping")


# ---------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------
if __name__ == "__main__":
    board = Microbit(mode="BOTH", dev_mode=True)

    try:
        while True:
            cmd = input("> ")
            board.send(cmd)
    except KeyboardInterrupt:
        print("Exiting...")
