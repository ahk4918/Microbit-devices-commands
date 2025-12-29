import asyncio
import os
import sys
import threading
import requests
import serial
import serial.tools.list_ports
from typing import Optional
from bleak import BleakScanner, BleakClient

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
VERSION_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/DETAILS.TXT"
INTERPRETER_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/interpreter.hex"

UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # micro:bit -> PC
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # PC -> micro:bit

USB_KEYWORDS = [
    "micro:bit",
    "bbc",
    "daplink",
    "cmsis",
    "mbed",
    "serial",
    "usb serial device",
    "usb composite"
]


# ---------------------------------------------------------
# DRIVE DETECTION (NO LOCAL FILES)
# ---------------------------------------------------------
def find_microbit_drive():
    """
    Detects micro:bit by checking drive labels (Windows only).
    Works for V1 and V2. Requires: pip install pywin32
    """
    try:
        import win32api
        import win32file
    except ImportError:
        print("⚠ pywin32 is required for drive detection: pip install pywin32")
        return None

    drives = win32api.GetLogicalDriveStrings().split("\x00")

    for d in drives:
        if not d:
            continue
        try:
            dtype = win32file.GetDriveType(d)
            if dtype == win32file.DRIVE_REMOVABLE:
                label = win32api.GetVolumeInformation(d)[0].lower()
                if "microbit" in label or "mbed" in label or "daplink" in label:
                    return d
        except Exception:
            pass

    return None


# ---------------------------------------------------------
# VERSION CHECKING (NO LOCAL FILES)
# ---------------------------------------------------------
def get_remote_interpreter_version():
    """Reads first line of DETAILS.TXT from GitHub."""
    try:
        r = requests.get(VERSION_URL, timeout=5)
        r.raise_for_status()
        return r.text.splitlines()[0].strip()
    except Exception as e:
        print(f"Error checking remote interpreter version: {e}")
        return None


def get_installed_interpreter_version_from_microbit():
    """
    Reads version.txt directly from the micro:bit drive, if present.
    This assumes your interpreter drops a version.txt file there.
    If not present, returns None.
    """
    drive = find_microbit_drive()
    if not drive:
        return None

    version_file = os.path.join(drive, "version.txt")
    if not os.path.exists(version_file):
        return None

    try:
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


# ---------------------------------------------------------
# INTERPRETER FLASHING (NO LOCAL FILES)
# ---------------------------------------------------------
def flash_interpreter_direct():
    """
    Downloads interpreter.hex directly into the micro:bit drive.
    No local files are kept.
    """
    drive = find_microbit_drive()
    if not drive:
        print("❌ MICROBIT drive not found.")
        return False

    print("Downloading interpreter...")
    try:
        r = requests.get(INTERPRETER_URL, timeout=10, stream=True)
        r.raise_for_status()
    except Exception as e:
        print(f"Interpreter download failed: {e}")
        return False

    dest = os.path.join(drive, "interpreter.hex")
    print(f"Flashing interpreter to {dest}...")

    try:
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    f.write(chunk)
        print("Interpreter copied. Micro:bit will reboot and flash.")
        return True
    except Exception as e:
        print(f"Interpreter flash failed: {e}")
        return False


def perform_interpreter_update():
    """
    Compares installed interpreter version (from micro:bit drive) with remote version.
    Prompts the user and flashes interpreter.hex if they agree.
    """
    remote = get_remote_interpreter_version()
    if not remote:
        print("⚠️ Could not check remote interpreter version.")
        return

    installed = get_installed_interpreter_version_from_microbit()
    if not installed:
        print("⚠️ Could not read installed interpreter version from micro:bit.")
        installed = "unknown"

    print(f"\nInstalled interpreter: {installed}")
    print(f"Available interpreter: {remote}")

    if installed == remote:
        print("Interpreter is already up to date.")
        return

    choice = input("Update interpreter now? (y/n): ").strip().lower()
    if choice != "y":
        return

    if flash_interpreter_direct():
        print("Interpreter update complete. Restarting controller...")
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

        print(f"--- 2025 micro:bit Interpreter Controller (Mode: {mode}) ---")

        # Start async loop
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

        # Check for interpreter updates BEFORE connecting
        perform_interpreter_update()

        # Connect to micro:bit
        self.reconnect()

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
        print("\n[DEBUG] Available serial ports:")
        for p in serial.tools.list_ports.comports():
            print(f" - {p.device}: {p.description}")

        # SERIAL
        if self.mode in ["BOTH", "SERIAL"]:
            for p in serial.tools.list_ports.comports():
                desc = (p.description or "").lower()
                if any(k in desc for k in USB_KEYWORDS):
                    try:
                        self.ser = serial.Serial(p.device, 115200, timeout=1)
                        self.current_mode = "SERIAL"
                        self._start_serial_listener()
                        print(f"Status: Connected via USB ({p.device})")
                        return
                    except Exception as e:
                        print(f"USB open failed: {e}")

        # BLE
        if self.mode in ["BOTH", "BLE"]:
            future = asyncio.run_coroutine_threadsafe(self._connect_ble(), self.loop)
            try:
                if future.result(timeout=35):
                    self.current_mode = "BLE"
                    print("Status: Connected via Bluetooth")
                    return
            except Exception as e:
                print(f"BLE connection error: {e}")

        print("Status: Connection failed.")

    async def _connect_ble(self):
        print("Scanning for BLE devices...")
        devices = await BleakScanner.discover(timeout=10.0)

        candidates = []
        for d in devices:
            name = (d.name or "").lower()
            if "micro" in name or "bit" in name or "bbc" in name:
                candidates.append(d)

        if not candidates:
            print("No BLE micro:bit found.")
            return False

        target = candidates[0]
        print(f"Connecting to BLE device: {target.name} [{target.address}]")

        self.ble_client = BleakClient(target)
        await self.ble_client.connect()

        try:
            await self.ble_client.start_notify(TX_UUID, self._on_data_received)
            self.active_rx = RX_UUID
            return True
        except Exception:
            try:
                await self.ble_client.start_notify(RX_UUID, self._on_data_received)
                self.active_rx = TX_UUID
                return True
            except Exception as e:
                print(f"Failed to start BLE notifications: {e}")
                return False

    # ---------------------------
    # Data Handling
    # ---------------------------
    def _on_data_received(self, handle, data):
        if isinstance(data, (bytes, bytearray)):
            msg = data.decode(errors="ignore").strip()
        else:
            msg = str(data).strip()

        if msg:
            print(f"\n[MICROBIT]: {msg}\n> ", end="")

    def _start_serial_listener(self):
        def listen():
            while self.ser and self.ser.is_open:
                try:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        self._on_data_received(None, line)
                except Exception:
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

    # Convenience wrappers for your interpreter commands
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
    def version(self): self.send("version")


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
