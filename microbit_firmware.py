# Version 2026.01.1
# Micro:bit device commands over Serial and Bluetooth UART

try:
    from microbit import *
    import music
except ImportError:
    # Fallback for PC testing - these won't be used during flashing
    pass

cmd = ""

def reply(msg):
    try:
        bluetooth.send(msg)
    except:
        pass
    print(msg)

def process_command(msg_input):
    global cmd
    
    raw_msg = msg_input.strip().lower()
    if len(raw_msg) == 0:
        return
    
    parts = raw_msg.split(" ")
    cmd = parts[0]
    
    # --- SENSOR COMMANDS ---
    if cmd == "get_sensor":
        if len(parts) < 2:
            return
        
        _type = parts[1]
        if _type == "temp":
            reply(str(microbit_temp()))
        elif _type == "light":
            reply(str(display.read_light_level()))
        elif _type == "accel":
            reply(str(accelerometer.get_strength()))
        elif _type == "compass":
            reply(str(compass.heading()))
    
    # --- PIN COMMANDS ---
    elif cmd == "get_pin":
        if len(parts) < 2:
            return
        
        p_name = parts[1]
        val = 0
        if p_name == "p0":
            val = pin0.read_analog()
        elif p_name == "p1":
            val = pin1.read_analog()
        elif p_name == "p2":
            val = pin2.read_analog()
        
        reply("PIN " + p_name + ": " + str(val))
    
    elif cmd == "pin":
        if len(parts) < 4:
            return
        
        mode = parts[1]
        p_label = parts[2]
        v = int(parts[3])
        
        if mode == "d":
            if p_label == "p0":
                pin0.write_digital(v)
            elif p_label == "p1":
                pin1.write_digital(v)
            elif p_label == "p2":
                pin2.write_digital(v)
        else:
            if p_label == "p0":
                pin0.write_analog(v)
            elif p_label == "p1":
                pin1.write_analog(v)
            elif p_label == "p2":
                pin2.write_analog(v)
    
    # --- MUSIC / TONE ---
    elif cmd == "tone":
        if len(parts) < 3:
            return
        
        freq = int(parts[1])
        dur = int(parts[2])
        music.play(music.POWER_UP)
    
    # --- LED MATRIX COMMANDS ---
    elif cmd == "print":
        text = ""
        for i in range(1, len(parts)):
            text += parts[i] + " "
        display.scroll(text.strip())
    
    elif cmd == "plot":
        if len(parts) < 3:
            return
        display.set_pixel(int(parts[1]), int(parts[2]), 9)
    
    elif cmd == "unplot":
        if len(parts) < 3:
            return
        display.set_pixel(int(parts[1]), int(parts[2]), 0)
    
    elif cmd == "toggle":
        if len(parts) < 3:
            return
        x = int(parts[1])
        y = int(parts[2])
        current = display.get_pixel(x, y)
        display.set_pixel(x, y, 0 if current else 9)
    
    # --- SYSTEM COMMANDS ---
    elif cmd == "clear":
        display.clear()
    
    elif cmd == "reset":
        display.clear()
        pin0.write_analog(0)
        pin1.write_analog(0)
        pin2.write_analog(0)
        music.stop()
        reply("RESET_OK")
    
    elif cmd == "ping":
        reply("pong")
    
    elif cmd == "version":
        reply("microbit_V2026.01.1")

def microbit_temp():
    """Get temperature in Celsius"""
    return int(temperature())

# Initialization
display.show(Image.SMALL_DIAMOND)

# Serial input handler
while True:
    if uart.any():
        msg = uart.readline()
        if msg:
            process_command(msg.decode())
    sleep(100)