#websocket.py
import serial, time, serial.tools.list_ports
#Check for firmware updates in Microbit firmware microbit_V2026.01.0.ts using github link
github_link = "https://github.com/ahk4918/Microbit-devices-commands/blob/main/microbit_V2026.01.0.ts"

#Get current firmware version
def autodetect_microbit_version(serial_port: serial.Serial) -> str:
    for p in serial.tools.list_ports.comports():
        if "Microbit" in p.description:
            serial_port.port = p.device
            serial_port.baudrate = 115200
            serial_port.timeout = 1
            serial_port.open()
            break
    try:
        serial_port.write(b"version\n")
        time.sleep(1)
        version = serial_port.readline().decode().strip()
        return version
    except Exception as e:
        print(f"Error detecting Microbit version: {e}")
        return "unknown"

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

# Get the code to flash to microbit from the github link using makecode online compiler
def download_firmware():
    try:
        response = requests.get(github_link)
        if response.status_code == 200:
            with open("microbit_firmware.ts", "w") as f:
                f.write(response.text)
            print("Firmware downloaded successfully.")
        else:
            print("Failed to download firmware.")
    except Exception as e:
        print(f"Error downloading firmware: {e}")