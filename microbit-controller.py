import asyncio
import os
import sys
import threading
import signal
import time
import subprocess
from typing import Optional

import requests
import serial
import serial.tools.list_ports
from bleak import BleakScanner, BleakClient

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

VERSION_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/DETAILS.TXT"
INTERPRETER_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/microbit-interpreter.hex"

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
    "usb composite",
]

KNOWN_VIDS = {0x0D28}  # mbed / DAPLink VID


# ---------------------------------------------------------
# DRIVE DETECTION
# ---------------------------------------------------------
def find_microbit_drive():
    try:
        import win32api # type: ignore
        import win32file# type: ignore
    except ImportError:
        print("⚠ pywin32 required for drive detection: pip install pywin32")
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
# NETWORK HELPERS
# ---------------------------------------------------------
def safe_download(url: str, attempts: int = 3, stream: bool = False):
    for i in range(attempts):
        try:
            r = requests.get(url, timeout=10, stream=stream)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"Download attempt {i + 1} failed: {e}")
            if i < attempts - 1:
                time.sleep(1.2)
    return None


# ---------------------------------------------------------
# VERSION CHECKING (REMOTE)
# ---------------------------------------------------------
def get_remote_interpreter_version() -> Optional[str]:
    """
    Remote version is taken from the first line of the GitHub DETAILS.TXT, e.g.:
    'Firmware Version 2026.01.3'
    We parse out '2026.01.3'.
    """
    r = safe_download(VERSION_URL, stream=False)
    if not r:
        return None

    try:
        first_line = r.text.splitlines()[0].strip().lstrip("\ufeff")
        parts = first_line.split()
        if not parts:
            return None
        # Assume version is the last token
        return parts[-1]
    except Exception:
        return None
# ---------------------------------------------------------
# HEX VALIDATION
# ---------------------------------------------------------
def validate_hex_file(path: str) -> bool:
    """
    Validates that a HEX file is safe to flash to a micro:bit.
    If validation fails:
      - Saves the entire file to invalid_hex_dump.txt
      - Prints the exact line number and content that failed
    """
    if not os.path.exists(path):
        print("❌ HEX validation failed: file does not exist.")
        return False

    size = os.path.getsize(path)
    if size < 1024:
        print("❌ HEX validation failed: file too small.")
        return False

    has_ext_addr = False
    eof_ok = False

    # Read all lines first so we can dump them if needed
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"❌ HEX validation failed: cannot read file: {e}")
        return False

    # Helper to dump file and show error line
    def fail(reason: str, line_num: int = None, line: str = None):#type: ignore
        dump_path = "invalid_hex_dump.txt"
        with open(dump_path, "w", encoding="utf-8") as dump:
            dump.writelines(lines)

        print(f"\n❌ HEX validation failed: {reason}")
        print(f"📄 Full file saved to: {dump_path}")

        if line_num is not None:
            print(f"🔍 Error at line {line_num}:")
            print(f"    {line.rstrip()}")
        return False

    # Validate each line
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # Must start with ':'
        if not line.startswith(":"):
            return fail("line missing ':' prefix", idx, line)

        # Check EOF record
        if line.upper() == ":00000001FF":
            eof_ok = True

        # Check extended linear address record
        if line.startswith(":02000004"):
            has_ext_addr = True

        # Basic Intel HEX format
        try:
            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)
        except Exception:
            return fail("malformed Intel HEX record", idx, line)

        # Length check
        expected_len = 11 + byte_count * 2
        if len(line) != expected_len:
            return fail(
                f"incorrect line length (expected {expected_len}, got {len(line)})",
                idx,
                line,
            )

    if not eof_ok:
        return fail("missing EOF record ':00000001FF'")

    if not has_ext_addr:
        return fail("missing extended linear address record ':02000004xxxxxx'")

    print("✔ HEX file validated successfully.")
    return True

# ---------------------------------------------------------
# FLASH INTERPRETER
# ---------------------------------------------------------
def flash_interpreter_direct() -> bool:
    drive = find_microbit_drive()
    if not drive:
        print("❌ MICROBIT drive not found.")
        return False

    print("Downloading interpreter (non-streaming)...")
    r = safe_download(INTERPRETER_URL, stream=False)
    if not r:
        print("❌ Could not download interpreter after retries.")
        return False

    temp_path = os.path.join(drive, "microbit-interpreter.tmp")
    final_path = os.path.join(drive, "microbit-interpreter.hex")

    print(f"Flashing interpreter to {final_path}...")

    try:
        # Write entire file in one chunk (prevents chunk corruption)
        with open(temp_path, "wb") as f:
            f.write(r.content)
            f.flush()
            os.fsync(f.fileno())

        # Optional: hide temp file on Windows
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            FILE_ATTRIBUTE_SYSTEM = 0x04
            ctypes.windll.kernel32.SetFileAttributesW(
                temp_path, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
            )
        except Exception:
            pass

        # Move into place atomically
        os.replace(temp_path, final_path)

        # Basic size check
        size = os.path.getsize(final_path)
        if size < 1024:
            print("❌ Flash failed: resulting file too small.")
            return False

        # Validate HEX structure
        if not validate_hex_file(final_path):
            print("❌ Interpreter HEX failed validation. Aborting flash.")
            return False

        # Allow Windows to finish writing to USB
        time.sleep(0.4)

        print("Interpreter copied. Micro:bit will reboot and flash.")
        return True

    except Exception as e:
        print(f"Flash failed: {e}")
        return False

# ---------------------------------------------------------
# SAFE RESTART
# ---------------------------------------------------------
def restart_script():
    print("Restarting controller...")
    script = os.path.abspath(__file__)
    subprocess.Popen([sys.executable, script])
    sys.exit(0)


# ---------------------------------------------------------
# MICROBIT CONTROLLER
# ---------------------------------------------------------
class Microbit:
    def __init__(self, mode: str = "BOTH", dev_mode: bool = False, version_check: bool = True):
        self.dev_mode = dev_mode
        self.version_check = version_check
        self.mode = mode.upper()
        self.current_mode: Optional[str] = None

        self.ser: Optional[serial.Serial] = None
        self.ble_client: Optional[BleakClient] = None
        self.active_rx = RX_UUID

        self._serial_lock = threading.Lock()

        # Version query synchronization
        self._waiting_for_version = False
        self._version_event = threading.Event()
        self._version_value: Optional[str] = None

        print(f"--- micro:bit Interpreter Controller (Mode: {self.mode}) ---")

        # Start async event loop in background thread
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

        # Connect first (we need a connection to query installed version)
        self.reconnect()

        # Perform version check after connection
        if self.version_check and self.current_mode is not None:
            self.perform_interpreter_update()

    # ---------------------------
    # LOGGING
    # ---------------------------
    def log(self, msg: str):
        if self.dev_mode:
            print(f"[DEBUG] {msg}")

    # ---------------------------
    # ASYNC LOOP
    # ---------------------------
    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    # ---------------------------
    # CONNECTION
    # ---------------------------
    def reconnect(self):
        print("\nScanning for micro:bit devices...")

        # USB first
        if self.mode in ["BOTH", "SERIAL"]:
            if self._try_connect_serial():
                return

        # BLE next
        if self.mode in ["BOTH", "BLE"]:
            future = asyncio.run_coroutine_threadsafe(self._connect_ble(), self.loop)
            try:
                if future.result(timeout=35):
                    self.current_mode = "BLE"
                    print("Connected via Bluetooth.")
                    return
            except Exception as e:
                self.log(f"BLE connection error: {e}")

        print("Connection failed.")
        self.current_mode = None

    def _try_connect_serial(self) -> bool:
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            vid = getattr(p, "vid", None)

            matches_keyword = any(k in desc for k in USB_KEYWORDS)
            matches_vid = vid in KNOWN_VIDS if vid is not None else False

            if not (matches_keyword or matches_vid):
                continue

            try:
                self.ser = serial.Serial(p.device, 115200, timeout=1)
                self.current_mode = "SERIAL"
                self._start_serial_listener()
                print(f"Connected via USB ({p.device})")
                return True
            except Exception as e:
                self.log(f"Failed to open serial port {p.device}: {e}")

        return False

    async def _connect_ble(self) -> bool:
        print("Scanning for BLE devices...")
        try:
            devices = await BleakScanner.discover(timeout=10.0)
        except Exception as e:
            print(f"BLE scan failed: {e}")
            return False

        candidates = [d for d in devices if "micro" in (d.name or "").lower()]

        if not candidates:
            print("No BLE micro:bit found.")
            return False

        target = candidates[0]
        print(f"Connecting to {target.name} [{target.address}]")

        self.ble_client = BleakClient(target)

        try:
            await self.ble_client.connect()
        except Exception as e:
            print(f"BLE connection failed: {e}")
            return False

        try:
            await self.ble_client.start_notify(TX_UUID, self._on_data_received)
            self.active_rx = RX_UUID
            print("BLE notifications on TX_UUID, writing to RX_UUID.")
            return True
        except Exception:
            self.log("TX notify failed, trying RX...")

        try:
            await self.ble_client.start_notify(RX_UUID, self._on_data_received)
            self.active_rx = TX_UUID
            print("BLE notifications on RX_UUID, writing to TX_UUID.")
            return True
        except Exception as e:
            print(f"BLE notify setup failed: {e}")
            try:
                if self.ble_client and self.ble_client.is_connected:
                    await self.ble_client.disconnect()
            except Exception:
                pass
            self.ble_client = None
            return False

    # ---------------------------
    # DATA HANDLING
    # ---------------------------
    def _on_data_received(self, handle, data):
        if isinstance(data, (bytes, bytearray)):
            msg = data.decode(errors="ignore").strip()
        else:
            msg = str(data).strip()

        if not msg:
            return

        # If we are currently waiting for a version response, capture this message
        if self._waiting_for_version and self._version_value is None:
            self._version_value = msg
            self._waiting_for_version = False
            self._version_event.set()
            self.log(f"Captured version response: {msg}")
            return

        print(f"\n[MICROBIT]: {msg}\n> ", end="", flush=True)

    def _start_serial_listener(self):
        def listen():
            while True:
                with self._serial_lock:
                    if not self.ser or not self.ser.is_open:
                        break
                    try:
                        line = self.ser.readline().decode(errors="ignore").strip()
                    except Exception:
                        break

                if line:
                    self._on_data_received(None, line)

            print("\n[INFO] Serial disconnected. Reconnecting...")
            self.ser = None
            self.current_mode = None
            self.reconnect()

        threading.Thread(target=listen, daemon=True).start()

    # ---------------------------
    # COMMANDS
    # ---------------------------
    def send(self, cmd: str):
        msg = (cmd.strip() + "\n").encode()

        if self.current_mode == "SERIAL" and self.ser:
            try:
                with self._serial_lock:
                    self.ser.write(msg)
            except Exception:
                print("Serial write failed. Reconnecting...")
                self.reconnect()

        elif self.current_mode == "BLE" and self.ble_client:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.ble_client.write_gatt_char(self.active_rx, msg, response=False),
                    self.loop,
                )
            except Exception:
                print("BLE write failed. Reconnecting...")
                self.reconnect()

        else:
            print("Not connected. Attempting to reconnect...")
            self.reconnect()

    # ---------------------------
    # VERSION QUERY (INSTALLED)
    # ---------------------------
    def get_installed_interpreter_version(self, timeout: float = 3.0) -> Optional[str]:
        """
        Ask the micro:bit for its interpreter version by sending 'version'
        and waiting for the next message. Assumes the interpreter replies
        with only the version string, e.g. '2026.01.3'.
        """
        if self.current_mode is None:
            self.reconnect()
            if self.current_mode is None:
                print("⚠ Could not connect to micro:bit to read installed version.")
                return None

        # Prepare to capture the version response
        self._version_event.clear()
        self._version_value = None
        self._waiting_for_version = True

        # Short delay to ensure interpreter is ready
        time.sleep(0.3)

        # Send version command
        self.send("version")

        # Wait for version response
        if not self._version_event.wait(timeout=timeout):
            print("⚠ Timed out waiting for version response from micro:bit.")
            self._waiting_for_version = False
            return None

        return self._version_value

    # ---------------------------
    # UPDATE LOGIC
    # ---------------------------
    def perform_interpreter_update(self):
        installed = self.get_installed_interpreter_version()
        remote = get_remote_interpreter_version()

        print(f"\nInstalled interpreter: {installed}")
        print(f"Available interpreter: {remote}")

        if not remote:
            print("⚠ Could not check remote version.")
            return

        if installed == remote:
            print("Interpreter is up to date.")
            return

        print("Updating interpreter to latest version...")
        if flash_interpreter_direct():
            print("Update complete. Restarting controller...")
            restart_script()
        else:
            print("Update failed. Keeping current interpreter.")

if __name__ == "__main__":
    try:
        controller = Microbit(mode="BOTH", dev_mode=True, version_check=False)

        print("\nType commands to send to the micro:bit. Type 'exit' to quit.")
        while True:
            cmd = input("> ").strip()
            if cmd.lower() in ["exit", "quit"]:
                print("Exiting...")
                break
            if cmd:
                controller.send(cmd)
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        try:
            if controller.ble_client and controller.ble_client.is_connected:
                asyncio.run_coroutine_threadsafe(
                    controller.ble_client.disconnect(), controller.loop
                )
        except Exception:
            pass