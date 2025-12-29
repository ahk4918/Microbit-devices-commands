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
# DRIVE DETECTION
# ---------------------------------------------------------
def find_microbit_drive():
    try:
        import win32api
        import win32file
    except ImportError:
        print("⚠ pywin32 required: pip install pywin32")
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
        except:
            pass

    return None


# ---------------------------------------------------------
# VERSION CHECKING
# ---------------------------------------------------------
def get_remote_interpreter_version():
    try:
        r = requests.get(VERSION_URL, timeout=5)
        r.raise_for_status()
        return r.text.splitlines()[0].strip()
    except:
        return None


def get_installed_interpreter_version_from_microbit():
    drive = find_microbit_drive()
    if not drive:
        return None

    version_file = os.path.join(drive, "version.txt")
    if not os.path.exists(version_file):
        return None

    try:
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except:
        return None


# ---------------------------------------------------------
# FLASH INTERPRETER (TEMP-FILE FIX)
# ---------------------------------------------------------
def flash_interpreter_direct():
    drive = find_microbit_drive()
    if not drive:
        print("❌ MICROBIT drive not found.")
        return False

    print("Downloading interpreter...")
    try:
        r = requests.get(INTERPRETER_URL, timeout=10, stream=True)
        r.raise_for_status()
    except Exception as e:
        print(f"Download failed: {e}")
        return False

    temp_path = os.path.join(drive, "interpreter.tmp")
    final_path = os.path.join(drive, "interpreter.hex")

    print(f"Flashing interpreter to {final_path}...")

    try:
        # Write to temp file
        with open(temp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    f.write(chunk)

        # Hide temp file so Windows ignores it
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            FILE_ATTRIBUTE_SYSTEM = 0x04
            ctypes.windll.kernel32.SetFileAttributesW(temp_path, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
        except:
            pass

        # Rename to .hex
        os.replace(temp_path, final_path)

        print("Interpreter copied. Micro:bit will reboot and flash.")
        return True

    except Exception as e:
        print(f"Flash failed: {e}")
        return False


# ---------------------------------------------------------
# SAFE RESTART
# ---------------------------------------------------------
def restart_script():
    os.system("python microbit-controller.py")
    sys.exit(0)


# ---------------------------------------------------------
# UPDATE LOGIC
# ---------------------------------------------------------
def perform_interpreter_update():
    remote = get_remote_interpreter_version()
    installed = get_installed_interpreter_version_from_microbit()

    print(f"\nInstalled interpreter: {installed}")
    print(f"Available interpreter: {remote}")

    if not remote:
        print("⚠ Could not check remote version.")
        return

    if installed == remote:
        print("Interpreter is up to date.")
        return

    choice = input("Update interpreter now? (y/n): ").strip().lower()
    if choice != "y":
        return

    if flash_interpreter_direct():
        print("Update complete. Restarting controller...")
        restart_script()


# ---------------------------------------------------------
# MICROBIT CONTROLLER
# ---------------------------------------------------------
class Microbit:
    def __init__(self, mode="BOTH", dev_mode=False):
        self.dev_mode = dev_mode
        self.mode = mode.upper()
        self.current_mode = None
        self.ser: Optional[serial.Serial] = None
        self.ble_client: Optional[BleakClient] = None
        self.active_rx = RX_UUID

        print(f"--- micro:bit Interpreter Controller (Mode: {mode}) ---")

        # Start async loop
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

        # Check for interpreter updates
        perform_interpreter_update()

        # Connect
        self.reconnect()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # ---------------------------
    # CONNECTION
    # ---------------------------
    def reconnect(self):
        print("\n[DEBUG] Serial ports:")
        for p in serial.tools.list_ports.comports():
            print(f" - {p.device}: {p.description}")

        # USB
        if self.mode in ["BOTH", "SERIAL"]:
            for p in serial.tools.list_ports.comports():
                desc = (p.description or "").lower()
                if any(k in desc for k in USB_KEYWORDS):
                    try:
                        self.ser = serial.Serial(p.device, 115200, timeout=1)
                        self.current_mode = "SERIAL"
                        self._start_serial_listener()
                        print(f"Connected via USB ({p.device})")
                        return
                    except:
                        pass

        # BLE
        if self.mode in ["BOTH", "BLE"]:
            future = asyncio.run_coroutine_threadsafe(self._connect_ble(), self.loop)
            try:
                if future.result(timeout=35):
                    self.current_mode = "BLE"
                    print("Connected via Bluetooth")
                    return
            except:
                pass

        print("Connection failed.")

    async def _connect_ble(self):
        print("Scanning for BLE devices...")
        devices = await BleakScanner.discover(timeout=10.0)

        candidates = [d for d in devices if "micro" in (d.name or "").lower()]

        if not candidates:
            print("No BLE micro:bit found.")
            return False

        target = candidates[0]
        print(f"Connecting to {target.name} [{target.address}]")

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
    # DATA HANDLING
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
                except:
                    break

        threading.Thread(target=listen, daemon=True).start()

    # ---------------------------
    # COMMANDS
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
