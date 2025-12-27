#websocket.py
#Check for firmware updates in Microbit firmware microbit_V2026.01.0.ts using github link
github_link = "https://github.com/ahk4918/Microbit-devices-commands/blob/main/microbit_V2026.01.0.ts"

#Check for updates in the link above and download the latest firmware if available.
import requests
def check_for_firmware_update(current_version: str) -> bool:
    try:
        response = requests.get(github_link)
        if response.status_code == 200:
            content = response.text
            # Extract version from the content (assuming it's in the filename)
            latest_version = content.split("microbit_V")[-1].split(".ts")[0]
            if latest_version > current_version:
                print(f"New firmware version available: {latest_version}")
                return True
            else:
                print("Firmware is up to date.")
                return False
        else:
            print("Failed to check for updates.")
            return False
    except Exception as e:
        print(f"Error checking for firmware update: {e}")
        return False

# Flash the code to Microbit into .hex file
#Use uflash tool to flash the firmware to microbit
import os
import uflash
def flash_firmware_to_microbit(firmware_path: str):
    try:
        uflash.flash(firmware_path)
        print(f"Successfully flashed firmware from {firmware_path} to Microbit.")
    except Exception as e:
        print(f"Error flashing firmware: {e}")
        