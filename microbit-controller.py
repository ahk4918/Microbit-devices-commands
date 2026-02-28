#!/usr/bin/env python3
import sys, time, threading, os, requests, serial, serial.tools.list_ports
from packaging.version import Version

DEFAULT_BAUD = 115200

FIRMWARE_V1_URL = (
    "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/V1%20Interpreter.hex"
)

FIRMWARE_V2_URL = (
    "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/V2%20Interpreter.hex"
)

DETAILS_URL = (
    "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/DETAILS.TXT"
)

BLE_DEVICE_NAME_PREFIX = "BBC micro:bit"
BLE_UART_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
BLE_UART_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


class Microbit:
    def __init__(self, baudrate=115200, allow_update=True, dev=False):
        self.mode = None
        self.usb_ser = None
        self.baudrate = baudrate
        self.allow_update = allow_update
        self.dev = dev

        self.ble_client = None
        self.ble_rx_buffer = []
        self.ble_lock = threading.Lock()

        # Hardware type: "microbit-v1" or "microbit-v2" or None
        self.hw_type = None
        # Feature flags based on hardware
        self.features = {
            "ble": True,
            "tone": True,
            "sound": True,
            "accel": True,
            "compass": True,
        }

        import asyncio
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # ---------- DEV LOG ----------
    def _devlog(self, msg):
        if self.dev:
            print(f"[DEV] {msg}")

    # ---------- EVENT LOOP ----------
    def _run_loop(self):
        import asyncio
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ---------- FEATURE RESTRICTIONS ----------
    def apply_feature_restrictions(self, hw_type):
        self.hw_type = hw_type
        if hw_type == "microbit-v1":
            # Strict: no BLE, no V2-only features
            self.features["ble"] = False
            self.features["tone"] = False
            self.features["sound"] = False
            self.features["accel"] = False
            self.features["compass"] = False
            self._devlog("Applied V1 feature restrictions")
        elif hw_type == "microbit-v2":
            # Full feature set
            self.features["ble"] = True
            self.features["tone"] = True
            self.features["sound"] = True
            self.features["accel"] = True
            self.features["compass"] = True
            self._devlog("Applied V2 full feature set")
        else:
            self._devlog("Unknown hardware type; leaving features default")

    # ---------- USB ----------
    def connect_usb(self):
        self._devlog("Scanning USB ports...")

        for p in serial.tools.list_ports.comports():
            port = p.device
            self._devlog(f"Trying USB port {port}")

            try:
                ser = serial.Serial(port, DEFAULT_BAUD, timeout=0.2)
            except Exception as e:
                self._devlog(f"Failed to open {port}: {e}")
                continue

            # Retry handshake several times
            got_pong = False
            for attempt in range(5):
                try:
                    ser.write(b"ping\n")
                    time.sleep(0.15)
                    out = ser.read(64).decode(errors="ignore")
                    self._devlog(f"USB RX attempt {attempt+1}: {out!r}")

                    if "pong" in out.lower():
                        got_pong = True
                        break

                except Exception as e:
                    self._devlog(f"USB error on attempt {attempt+1}: {e}")

                time.sleep(0.15)

            if got_pong:
                self.usb_ser = ser
                self.mode = "usb"
                print(f"Connected via USB: {port}")
                self._devlog("USB handshake OK")
                return True

            # Silent device fallback
            self._devlog(f"No pong on {port}, but port is alive — treating as silent device")
            self.usb_ser = ser
            self.mode = "usb"
            return True

        self._devlog("USB scan complete, no device found")
        return False

    def _usb_write(self, line):
        if self.usb_ser:
            self._devlog(f"USB TX: {line}")
            self.usb_ser.write((line + "\n").encode())

    def _usb_read(self):
        if not self.usb_ser:
            return ""
        out = []
        try:
            while True:
                chunk = self.usb_ser.read(1024)
                if not chunk:
                    break
                out.append(chunk.decode(errors="ignore"))
        except:
            pass
        text = "".join(out)
        if text:
            self._devlog(f"USB RX: {text!r}")
        return text

    # ---------- BLE ----------
    async def _ble_notify(self, sender, data):
        text = data.decode(errors="ignore")
        self._devlog(f"BLE NOTIFY: {text!r}")
        with self.ble_lock:
            self.ble_rx_buffer.append(text)

    async def _ble_try_device(self, d):
        from bleak import BleakClient
        import asyncio

        self._devlog(f"Attempting BLE connection to {d.address}")

        client = BleakClient(d.address)
        try:
            await client.connect(timeout=10.0)
            self._devlog("BLE connected")
        except Exception as e:
            self._devlog(f"BLE connect failed: {e}")
            return False

        try:
            await client.start_notify(BLE_UART_TX_UUID, self._ble_notify)
            self._devlog("BLE notifications enabled")
        except Exception as e:
            self._devlog(f"BLE notify failed: {e}")
            return False

        try:
            await client.write_gatt_char(BLE_UART_RX_UUID, b"ping\n")
            self._devlog("BLE TX: ping")
            await asyncio.sleep(0.2)
        except Exception as e:
            self._devlog(f"BLE write failed: {e}")
            return False

        with self.ble_lock:
            text = "".join(self.ble_rx_buffer)
            self.ble_rx_buffer.clear()

        self._devlog(f"BLE handshake RX: {text!r}")

        if "pong" in text.lower():
            self.ble_client = client
            self.mode = "ble"
            print(f"Connected via BLE: {d.address}")
            self._devlog("BLE handshake OK")
            return True

        await client.disconnect()
        self._devlog("BLE handshake failed, disconnected")
        return False

    async def _ble_open_async(self):
        from bleak import BleakScanner
        self._devlog("Scanning BLE devices...")

        devices = await BleakScanner.discover(timeout=4.0)
        self._devlog(f"BLE scan found {len(devices)} devices")

        for d in devices:
            self._devlog(f"BLE device: name={d.name} addr={d.address}")
            if (d.name or "").startswith(BLE_DEVICE_NAME_PREFIX):
                self._devlog("Candidate micro:bit found")
                if await self._ble_try_device(d):
                    return True

        self._devlog("No BLE micro:bit found")
        return False

    def connect_ble(self):
        if not self.features.get("ble", True):
            self._devlog("BLE disabled by feature restrictions")
            return False

        import asyncio
        fut = asyncio.run_coroutine_threadsafe(self._ble_open_async(), self._loop)
        try:
            return fut.result()
        except Exception as e:
            self._devlog(f"BLE connect error: {e}")
            return False

    def _ble_write(self, line):
        import asyncio
        if not self.ble_client:
            return
        self._devlog(f"BLE TX: {line}")
        data = (line + "\n").encode()
        fut = asyncio.run_coroutine_threadsafe(
            self.ble_client.write_gatt_char(BLE_UART_RX_UUID, data),
            self._loop
        )
        try:
            fut.result()
        except Exception as e:
            self._devlog(f"BLE write error: {e}")

    def _ble_read(self):
        with self.ble_lock:
            if not self.ble_rx_buffer:
                return ""
            text = "".join(self.ble_rx_buffer)
            self.ble_rx_buffer.clear()
            self._devlog(f"BLE RX: {text!r}")
            return text

    # ---------- Unified connect ----------
    def connect(self):
        print("Trying USB...")
        if self.connect_usb():
            return True

        if self.features.get("ble", True):
            print("Trying BLE...")
            return self.connect_ble()

        return False

    def write(self, line):
        if self.mode == "usb":
            self._usb_write(line)
        elif self.mode == "ble":
            self._ble_write(line)

    def read(self):
        if self.mode == "usb":
            return self._usb_read()
        elif self.mode == "ble":
            return self._ble_read()
        return ""

    # ---------- DETAILS.TXT on device ----------
    def find_drive(self):
        self._devlog("Searching for MICROBIT drive...")

        if os.name == "nt":
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                d = f"{letter}:\\"
                if os.path.exists(os.path.join(d, "DETAILS.TXT")):
                    self._devlog(f"Found drive at {d}")
                    return d
            self._devlog("No drive found on Windows")
            return None

        for root in ["/media", "/mnt", "/Volumes"]:
            if not os.path.isdir(root):
                continue
            for name in os.listdir(root):
                p = os.path.join(root, name)
                if os.path.exists(os.path.join(p, "DETAILS.TXT")):
                    self._devlog(f"Found drive at {p}")
                    return p

        self._devlog("No drive found on Unix")
        return None

    def detect_device_from_details(self):
        drive = self.find_drive()
        if not drive:
            self._devlog("detect_device_from_details: no drive")
            return None

        path = os.path.join(drive, "DETAILS.TXT")
        self._devlog(f"Reading {path}")

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception as e:
            self._devlog(f"Failed to read DETAILS.TXT: {e}")
            return None

        self._devlog("Scanning DETAILS.TXT for board id")

        board_id = None
        for line in text.splitlines():
            line = line.strip()
            if "microbit.org/device" in line and "id=" in line:
                try:
                    after_id = line.split("id=", 1)[1]
                    board_id = after_id.split("&", 1)[0]
                    self._devlog(f"Parsed board id={board_id}")
                except Exception as e:
                    self._devlog(f"Failed to parse board id: {e}")
                break

        if not board_id:
            self._devlog("No board id found in DETAILS.TXT")
            return None

        if board_id.startswith("02"):
            self._devlog("Detected micro:bit V1 from board id prefix 02xx")
            return "microbit-v1"

        if board_id.startswith("99"):
            self._devlog("Detected micro:bit V2 from board id prefix 99xx")
            return "microbit-v2"

        if "microbit.org/device" in text:
            self._devlog(f"Unknown board id {board_id}, defaulting to microbit-v2")
            return "microbit-v2"

        self._devlog("DETAILS.TXT did not look like a micro:bit")
        return None

    # ---------- GitHub DETAILS.TXT parsing ----------
    def get_latest_versions(self):
        """
        Parse unified DETAILS.TXT from GitHub:
        Firmware Version V1: X.Y.Z
        Firmware Version V2: X.Y.Z
        """
        self._devlog("Fetching latest versions from server")
        latest_v1 = None
        latest_v2 = None
        try:
            r = requests.get(DETAILS_URL, timeout=10)
            for line in r.text.splitlines():
                line = line.strip()
                if line.lower().startswith("firmware version v1:"):
                    latest_v1 = line.split(":", 1)[1].strip()
                elif line.lower().startswith("firmware version v2:"):
                    latest_v2 = line.split(":", 1)[1].strip()
            self._devlog(f"Latest V1={latest_v1}, V2={latest_v2}")
        except Exception as e:
            self._devlog(f"Version fetch failed: {e}")
            return None, None
        return latest_v1, latest_v2

    # ---------- Device version ----------
    def get_device_version(self):
        self._devlog("Requesting device version")
        self.write("version")
        time.sleep(0.2)
        out = self.read()

        version = None
        dtype = None
        devtype = None

        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
            if line.startswith("Type:"):
                dtype = line.split(":", 1)[1].strip()
            if line.startswith("Device Type:"):
                devtype = line.split(":", 1)[1].strip()

        self._devlog(f"Device version={version}, type={dtype}, devtype={devtype}")
        return version, dtype, devtype

    # ---------- Flash ----------
    def flash(self, devtype):
        drive = self.find_drive()
        if not drive:
            print("No MICROBIT drive found.")
            self._devlog("flash: no drive found")
            return False

        self._devlog(f"Flashing device type {devtype}")

        if devtype == "microbit-v1":
            url = FIRMWARE_V1_URL
        elif devtype == "microbit-v2":
            url = FIRMWARE_V2_URL
        else:
            print("Unknown device type for flashing.")
            self._devlog("flash: unknown device type")
            return False

        self._devlog(f"Downloading interpreter from {url}")

        r = requests.get(url)
        if r.status_code != 200:
            print("Download failed.")
            self._devlog(f"Download failed: HTTP {r.status_code}")
            return False

        path = os.path.join(drive, "microbit-interpreter.hex")
        self._devlog(f"Writing HEX to {path}")

        with open(path, "wb") as f:
            f.write(r.content)

        print("Flashed. Waiting for reboot...")
        self._devlog("Flash complete")
        time.sleep(3)
        return True

    # ---------- Update / Version logic ----------
    def ensure_updated(self):
        latest_v1, latest_v2 = self.get_latest_versions()
        if not latest_v1 and not latest_v2:
            print("Could not fetch latest version info.")
            return True

        # Determine hardware type if not already known
        if not self.hw_type:
            hw = self.detect_device_from_details()
            if hw:
                self.apply_feature_restrictions(hw)
            else:
                print("Could not determine hardware type.")
                return False

        device, dtype, devtype = self.get_device_version()

        # If device is silent, fallback to flashing based on hardware type
        if not device:
            print("Device did not respond to version. Checking USB drive...")
            self._devlog("Device silent, using DETAILS.TXT fallback")
            if not self.hw_type:
                hw = self.detect_device_from_details()
                if not hw:
                    print("No micro:bit detected.")
                    return False
                self.apply_feature_restrictions(hw)
            devtype = self.hw_type
            print(f"Detected device by DETAILS.TXT: {devtype}")
            device = "0.0.0"
            dtype = "UNKNOWN"

        # Mismatch detection: V2 hardware running V1 interpreter
        # (Flexible behavior: warn + offer upgrade, but allow console)
        if self.hw_type == "microbit-v2" and devtype == "microbit-v1":
            print("Warning: V2 hardware is running V1 interpreter.")
            print("You can continue with limited features, or upgrade to V2 interpreter.")
            choice = input("Upgrade to V2 interpreter now? [y/N]: ").strip().lower()
            if choice == "y":
                print("Flashing V2 interpreter...")
                if not self.flash("microbit-v2"):
                    print("Flash failed.")
                    return False
                print("Waiting for micro:bit to reboot...")
                time.sleep(4)
                print("Reconnecting...")
                if not self.connect():
                    print("Reconnect failed after flashing.")
                    return False
                print("Re-checking version...")
                device2, _, devtype2 = self.get_device_version()
                if device2 and devtype2 == "microbit-v2":
                    print("Upgrade to V2 interpreter successful.")
                    device = device2
                    devtype = devtype2
                else:
                    print("Upgrade did not complete correctly; continuing anyway.")
            else:
                print("Continuing with V1 interpreter on V2 hardware (limited features).")

        # Choose correct latest version based on hardware type
        if self.hw_type == "microbit-v1":
            latest = latest_v1
        else:
            latest = latest_v2

        if not latest:
            print("No latest version defined for this hardware type.")
            return True

        try:
            if Version(device) >= Version(latest):
                print(f"Interpreter up to date ({device} >= {latest})")
                self._devlog("Interpreter already up to date")
                return True
        except Exception as e:
            print("Version parse error; skipping update.")
            self._devlog(f"Version parse error: {e}")
            return True

        print(f"Outdated interpreter: device={device}, latest={latest}")
        print("Updating...")
        self._devlog("Starting update process")

        # If devtype not known, use hardware type
        if not devtype:
            devtype = self.hw_type

        if not self.flash(devtype):
            return False

        print("Waiting for micro:bit to reboot...")
        time.sleep(4)

        print("Reconnecting...")
        if not self.connect():
            print("Reconnect failed after flashing.")
            self._devlog("Reconnect failed")
            return False

        print("Re-checking version...")
        device2, _, _ = self.get_device_version()
        if not device2:
            print("Device did not respond after update.")
            self._devlog("Device silent after update")
            return False

        try:
            if Version(device2) >= Version(latest):
                print("Update successful.")
                self._devlog("Update successful")
                return True
        except:
            return True

        print("Update failed: version did not change.")
        self._devlog("Update failed: version unchanged")
        return False

    # ---------- Console ----------
    def prepare_command(self, raw):
        if not raw:
            return None
        normalized = " ".join(raw.strip().split())
        if not normalized:
            return None
        return normalized

    def console(self):
        print("Connected. Type commands. Ctrl+C to exit.")
        try:
            while True:
                raw = input("> ")
                cmd = self.prepare_command(raw)
                if not cmd:
                    continue
                self._devlog(f"TX: {cmd}")
                self.write(cmd)
                time.sleep(0.1)
                out = self.read()
                if out:
                    self._devlog(f"RX: {out!r}")
                    print(out, end="")
        except KeyboardInterrupt:
            print("\nBye.")


def main():
    m = Microbit(dev=True)

    # Detect hardware type early and apply feature restrictions
    hw = m.detect_device_from_details()
    if hw:
        m.apply_feature_restrictions(hw)

    print("Connecting...")
    if not m.connect():
        print("Could not connect via USB/BLE. Checking USB drive...")

        devtype = m.detect_device_from_details()
        if not devtype:
            print("No micro:bit detected.")
            return

        m.apply_feature_restrictions(devtype)
        print(f"Detected device by DETAILS.TXT: {devtype}")
        print("Flashing interpreter...")

        if not m.flash(devtype):
            print("Flash failed.")
            return

        print("Waiting for reboot...")
        time.sleep(4)

        print("Reconnecting...")
        if not m.connect():
            print("Reconnect failed after flashing.")
            return

    print("Checking interpreter version...")
    if not m.ensure_updated():
        print("Update failed.")
        return

    m.console()


if __name__ == "__main__":
    main()
