import requests
import os
import shutil

# URLs
version_url = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/main/details.txt"
firmware_url = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/main/firmware.hex"

# Local temp file
local_firmware = "firmware.hex"

# Microbit drive letter
microbit_drive = "D:\\"   # Ensure this is correct on your system

def download_firmware():
    print("Downloading firmware...")
    response = requests.get(firmware_url, timeout=10)
    response.raise_for_status()

    with open(local_firmware, "wb") as f:
        f.write(response.content)

    print("Firmware downloaded successfully.")
    return local_firmware

def flash_to_microbit(firmware_path):
    if not os.path.exists(microbit_drive):
        print("MICROBIT drive not found. Is it plugged in?")
        return False

    dest_path = os.path.join(microbit_drive, "firmware.hex")

    print(f"Copying firmware to {dest_path}...")
    shutil.copy(firmware_path, dest_path)

    print("Firmware copied. The micro:bit should reboot and flash automatically.")
    return True

def update_microbit():
    try:
        fw = download_firmware()
        flash_to_microbit(fw)
    except Exception as e:
        print(f"Error: {e}")

update_microbit()
