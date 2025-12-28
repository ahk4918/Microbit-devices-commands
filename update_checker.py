__version__ = "0.1.0"

import re
import time
import requests
import serial
import serial.tools.list_ports
import os
import shutil
import string
import sys
import tempfile

# Only check the online firmware TS file
GITHUB_RAW_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/microbit_firmware.ts"

def parse_version_from_text(text):
    m = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', text)
    return m.group(1).strip() if m else None

def parse_version_from_ts(text):
    """Extract version from TypeScript firmware file lines like '//  Version 2026.01.1'."""
    m = re.search(r'Version\s*([0-9A-Za-z\.\-]+)', text, re.IGNORECASE)
    return m.group(1).strip() if m else None

def find_local_firmware_ts():
    """Return path to microbit_firmware.ts in the same folder as this script (if present)."""
    base = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base, "microbit_firmware.ts")
    return candidate if os.path.isfile(candidate) else None

def get_firmware_ts_version():
    """Read local microbit_firmware.ts and return its embedded version string (if any)."""
    p = find_local_firmware_ts()
    if not p:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = f.read(2048)  # only need header area
        return parse_version_from_ts(data)
    except Exception:
        return None

def get_local_version():
    # read first few lines of this file to find version on top line
    try:
        with open(__file__, "r", encoding="utf-8") as f:
            first_chunk = "".join([next(f) for _ in range(5)])
        return parse_version_from_text(first_chunk)
    except Exception:
        return __version__

def get_github_version():
    """Fetch the online TypeScript firmware and parse its embedded version."""
    try:
        r = requests.get(GITHUB_RAW_URL, timeout=10)
        r.raise_for_status()
        return parse_version_from_ts(r.text)
    except Exception:
        return None

def download_github_raw_to_temp():
    """Download the online firmware TS to a temporary .ts file and return its path."""
    try:
        r = requests.get(GITHUB_RAW_URL, timeout=15)
        r.raise_for_status()
        fd, path = tempfile.mkstemp(suffix=".ts")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(r.text)
        return path
    except Exception:
        return None

def get_device_version():
    try:
        ports = serial.tools.list_ports.comports()
        for port in ports:
            desc = (port.description or "").upper()
            if "MICROBIT" in desc or "MICRO:BIT" in desc:
                ser = serial.Serial(port.device, 115200, timeout=1)
                time.sleep(2)
                ser.write(b"get_firmware_version\n")
                line = ser.readline().decode(errors="ignore").strip()
                ser.close()
                if line:
                    return line
        return None
    except Exception:
        return None

def find_microbit_drive():
    """Return root path of connected micro:bit mass storage (e.g. 'E:\\') or None."""
    for d in string.ascii_uppercase:
        root = f"{d}:\\"
        if not os.path.exists(root):
            continue
        try:
            for name in os.listdir(root):
                if name.upper() == "MICROBIT.HTM":
                    return root
        except Exception:
            continue
    return None

def flash_script_to_microbit(file_path, target_name=None):
    """
    Copy a file to the micro:bit drive to flash it.
    - file_path: path to .py/.hex/.uf2/.ts file or script to flash
    - target_name: optional filename to use on the device (defaults to basename or 'main.py' for .py)
    Returns True on success, False otherwise.
    """
    drive = find_microbit_drive()
    if not drive:
        print("Micro:bit drive not found.")
        return False
    if not os.path.isfile(file_path):
        print("Source file not found:", file_path)
        return False
    src_basename = os.path.basename(file_path)
    if not target_name:
        if file_path.lower().endswith((".hex", ".uf2", ".ts")):
            target_name = src_basename
        else:
            target_name = "main.py"
    dest = os.path.join(drive, target_name)
    try:
        # attempt atomic copy
        shutil.copy(file_path, dest)
        print(f"Flashed {target_name} to {drive}")
        return True
    except Exception as e:
        print("Failed to flash:", e)
        return False

def flash_current_script_as_main():
    """Flash this script to the micro:bit as main.py."""
    return flash_script_to_microbit(__file__, target_name="main.py")

# --- new helpers to use the provided microbit_firmware.ts as firmware script ---
def flash_local_firmware_ts(target_name="firmware.ts"):
    """Flash the local microbit_firmware.ts to the micro:bit drive as target_name."""
    src = find_local_firmware_ts()
    if not src:
        print("Local firmware script microbit_firmware.ts not found.")
        return False
    return flash_script_to_microbit(src, target_name=target_name)
# --- end new helpers ---

def compare_semver(a, b):
    if not a or not b: return None
    try:
        pa = [int(x) for x in re.sub(r'[^0-9.]', '', a).split('.') if x != '']
        pb = [int(x) for x in re.sub(r'[^0-9.]', '', b).split('.') if x != '']
        # normalize lengths
        L = max(len(pa), len(pb))
        pa += [0] * (L - len(pa)); pb += [0] * (L - len(pb))
        if pa == pb: return 0
        return 1 if pa > pb else -1
    except Exception:
        return None

def check_firmware_update():
    # Only check the online firmware TS file for repository version
    local = get_local_version()
    repo_version = get_github_version()
    device = get_device_version()

    print(f"Local checker version: {local or 'unknown'}")
    print(f"Repository firmware version: {repo_version or 'unknown'}")
    if repo_version:
        cmp = compare_semver(local, repo_version)
        if cmp == -1:
            print("A newer checker/firmware is available in repository.")
        elif cmp == 1:
            print("Local checker is newer than repository.")
        else:
            print("Checker is up to date with repository.")
    else:
        print("Could not fetch repository firmware version.")

    if device:
        print(f"Device firmware version: {device}")
        if repo_version:
            cmp2 = compare_semver(device, repo_version)
            if cmp2 == -1:
                print("Device firmware is older than repository firmware. Consider updating the device.")
            elif cmp2 == 1:
                print("Device firmware is newer than repository firmware.")
            else:
                print("Device firmware matches repository firmware.")
    else:
        print("Could not detect device firmware version.")
        print("Device firmware version not found. You can flash the local firmware script microbit_firmware.ts to the device:")
        print("  python update_checker.py flash-firmware")
        print("Or flash any file manually with:")
        print("  python update_checker.py flash <path>")
        print("See the repository README for flashing instructions.")

def print_usage():
    print("Usage:")
    print("  python update_checker.py             # check versions")
    print("  python update_checker.py flash-self  # flash this script as main.py")
    print("  python update_checker.py flash <path> # flash given file to micro:bit")
    print("  python update_checker.py flash-latest # download latest firmware TS from repo and flash to device")
    print("  python update_checker.py flash-firmware # flash local microbit_firmware.ts to device")

def main(argv):
    if len(argv) <= 1:
        check_firmware_update()
        return
    cmd = argv[1].lower()
    if cmd == "flash-self":
        ok = flash_current_script_as_main()
        if not ok:
            sys.exit(1)
    elif cmd == "flash":
        if len(argv) < 3:
            print("Missing file path.")
            print_usage()
            sys.exit(2)
        path = argv[2]
        ok = flash_script_to_microbit(path)
        if not ok:
            sys.exit(1)
    elif cmd == "flash-latest":
        temp = download_github_raw_to_temp()
        if not temp:
            print("Failed to download latest firmware TS.")
            sys.exit(1)
        try:
            ok = flash_script_to_microbit(temp, target_name=os.path.basename(temp))
            if not ok:
                sys.exit(1)
        finally:
            try:
                os.remove(temp)
            except Exception:
                pass
    elif cmd == "flash-firmware":
        ok = flash_local_firmware_ts(target_name="firmware.ts")
        if not ok:
            sys.exit(1)
    else:
        print_usage()
        sys.exit(2)

if __name__ == "__main__":
    main(sys.argv)
