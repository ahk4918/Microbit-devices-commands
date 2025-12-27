import asyncio
import threading
import time
import serial
import serial.tools.list_ports
from typing import Optional
from bleak import BleakScanner, BleakClient

# 2025 Standard Nordic UART UUIDs
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e" # micro:bit -> PC
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e" # PC -> micro:bit

class Microbit:
    def __init__(self, mode: str = "BOTH", dev_mode: bool = False):
        self.dev_mode = dev_mode
        print(f"--- 2025 micro:bit Hybrid Controller (Mode: {mode}) ---")
        
        self.mode = mode.upper()
        self.current_mode = None
        self.ser: Optional[serial.Serial] = None
        self.ble_client: Optional[BleakClient] = None
        self.active_rx = RX_UUID 
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()
        self.reconnect()

    def _dev_log(self, msg: str):
        if self.dev_mode: print(f"[DEV] {msg}")

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def reconnect(self):
        # 1. Serial Strategy
        if self.mode in ["BOTH", "SERIAL"]:
            self._dev_log("Checking Serial ports...")
            for p in serial.tools.list_ports.comports():
                if any(x in p.description for x in ["micro:bit", "mbed", "USB Serial"]):
                    try:
                        self.ser = serial.Serial(p.device, 115200, timeout=1)
                        self.current_mode = "SERIAL"
                        self._start_serial_listener()
                        print(f"Status: Connected via USB ({p.device})")
                        return
                    except: pass

        # 2. Bluetooth Strategy
        if self.mode in ["BOTH", "BLE"]:
            self._dev_log("Initiating BLE Discovery...")
            future = asyncio.run_coroutine_threadsafe(self._connect_ble(), self.loop)
            try:
                if future.result(timeout=35):
                    self.current_mode = "BLE"
                    print("Status: Connected via Bluetooth")
                    return
            except Exception as e:
                self._dev_log(f"BLE Connection Error: {e}")

        print("Status: Connection failed.")

    async def _connect_ble(self) -> bool:
        # Perform scan silently (logs only in dev_mode)
        self._dev_log("Scanning for 10 seconds...")
        devices = await BleakScanner.discover(timeout=10.0)
        
        candidates = []
        for d in devices:
            name = (d.name or "").lower()
            if "micro:bit" in name or "guzop" in name:
                candidates.append(d)
                self._dev_log(f"Found Candidate: {d.name} [{d.address}]")

        if not candidates:
            self._dev_log("Scan finished: No micro:bits found.")
            return False

        target_device = None
        if len(candidates) > 1:
            # ONLY prompt the user if more than one is found
            print(f"\n[SYSTEM] Multiple micro:bits detected ({len(candidates)}):")
            for i, dev in enumerate(candidates):
                print(f"  [{i}] {dev.name} ({dev.address})")
            
            while True:
                try:
                    choice = input("Select device index: ").strip()
                    idx = int(choice)
                    if 0 <= idx < len(candidates):
                        target_device = candidates[idx]
                        break
                except ValueError: pass
                print("Invalid selection. Please enter a number from the list.")
        else:
            # Single device found - connect silently
            target_device = candidates[0]
            self._dev_log(f"Single micro:bit found. Connecting to {target_device.name}...")

        self.ble_client = BleakClient(target_device)
        await self.ble_client.connect()

        # Role-Swap Fallback logic for 2025 OS stacks
        try:
            await self.ble_client.start_notify(TX_UUID, self._on_data_received)
            self.active_rx = RX_UUID
            self._dev_log("Standard Role Assignment: TX=0003, RX=0002")
            return True
        except:
            self._dev_log("Primary Notify failed. Swapping TX/RX roles...")
            try:
                await self.ble_client.start_notify(RX_UUID, self._on_data_received)
                self.active_rx = TX_UUID
                self._dev_log("Flipped Role Assignment: TX=0002, RX=0003")
                return True
            except: 
                return False

    def _on_data_received(self, handle, data):
        # Decode bytes/bytearray to clean string
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
                    if line: self._on_data_received(None, line)
                except: break
        threading.Thread(target=listen, daemon=True).start()

    def send(self, cmd: str):
        msg = (cmd.strip() + "\n").encode()
        if self.current_mode == "SERIAL" and self.ser:
            self.ser.write(msg)
        elif self.current_mode == "BLE" and self.ble_client:
            asyncio.run_coroutine_threadsafe(
                self.ble_client.write_gatt_char(self.active_rx, msg, response=False), 
                self.loop
            )

    def close(self):
        if self.ser: self.ser.close()
        if self.ble_client:
            asyncio.run_coroutine_threadsafe(self.ble_client.disconnect(), self.loop)

    def get_sensor(self, sensor_type: str):
        """Valid: temp, light, accel, compass"""
        self.send(f"get_sensor {sensor_type}")

    def get_pin(self, pin_name: str):
        """Reads analog: 'p0', 'p1', 'p2'"""
        self.send(f"get_pin {pin_name}")

    def tone(self, frequency: int, duration_ms: int):
        self.send(f"tone {frequency} {duration_ms}")

    def pin_write(self, p_type: str, pin: str, val: int):
        """p_type: 'd' or 'a'"""
        self.send(f"pin {p_type} {pin} {val}")

    def print_text(self, text: str):
        self.send(f"print {text}")

    def plot(self, x: int, y: int): self.send(f"plot {x} {y}")
    def unplot(self, x: int, y: int): self.send(f"unplot {x} {y}")
    def toggle(self, x: int, y: int): self.send(f"toggle {x} {y}")
    def clear(self): self.send("clear")
    def reset(self): self.send("reset")
    def ping(self): self.send("ping")

class Arduino:
    def __init__(self, baudrate: int = 115200, dev_mode: bool = False):
        self.dev_mode = dev_mode
        self.ser: Optional[serial.Serial] = None
        print(f"--- 2025 Arduino USB Controller ---")
        port = None
        for p in serial.tools.list_ports.comports():
            if "Arduino" in p.description or "USB Serial" in p.description:
                port = p.device
                break
        if port is None:
            print("Arduino not found. Check USB cable.")
            return 
        self.ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)  # Wait for Arduino to reboot
        self._dev_log(f"Connected to Arduino on {port} at {baudrate} baud.")

    def _dev_log(self, msg: str):
        if self.dev_mode: print(f"[DEV] {msg}")

    def send(self, cmd: str):
        message = (cmd.strip() + "\n").encode()
        self.ser.write(message) #type: ignore
        self._dev_log(f"Sent: {cmd.strip()}")
        self.read_response()

    def read_response(self) -> str:
        response = self.ser.readline().decode().strip() #type: ignore
        print(f"[ARDUINO]: {response}")
        return response

    def close(self):
        self.ser.close() #type: ignore
        self._dev_log("Serial connection closed.")

if __name__ == "__main__":
    # Example usage of Arduino class
    board = Arduino(dev_mode=True,baudrate=9600)
    if board.ser:
        try:
            while True:
                command = input("Enter command to send to Arduino: ")
                board.send(command)
        except KeyboardInterrupt:
            print("Exiting...")
        finally:
            board.close()
