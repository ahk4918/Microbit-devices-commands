def reply(msg: str):
    bluetooth.uart_write_line(msg)
    serial.write_line(msg)
# Initialization

def on_uart_data_received():
    process_command(bluetooth.uart_read_until(serial.delimiters(Delimiters.NEW_LINE)))
bluetooth.on_uart_data_received(serial.delimiters(Delimiters.NEW_LINE),
    on_uart_data_received)

def on_data_received():
    process_command(serial.read_line())
serial.on_data_received(serial.delimiters(Delimiters.NEW_LINE), on_data_received)

def process_command(msg_input: str):
    global cmd
    raw_msg = msg_input.trim().to_lower_case()
    if len(raw_msg) == 0:
        return
    parts = raw_msg.split(" ")
    # FIX: Get the first element (string) from the list
    cmd = parts[0]
    # --- SENSOR COMMANDS ---
    if cmd == "get_sensor":
        if len(parts) < 2:
            return
        _type = parts[1]
        if _type == "temp":
            reply("" + str(input.temperature()))
        elif _type == "light":
            reply("" + str(input.light_level()))
        elif _type == "accel":
            reply("" + str(input.acceleration(Dimension.STRENGTH)))
        elif _type == "compass":
            reply("" + str(input.compass_heading()))
    elif cmd == "get_pin":
        # --- PIN COMMANDS ---
        if len(parts) < 2:
            return
        p_name = parts[1]
        val = 0
        if p_name == "p0":
            val = pins.analog_read_pin(AnalogPin.P0)
        elif p_name == "p1":
            val = pins.analog_read_pin(AnalogPin.P1)
        elif p_name == "p2":
            val = pins.analog_read_pin(AnalogPin.P2)
        reply("PIN " + p_name + ": " + ("" + str(val)))
    elif cmd == "pin":
        if len(parts) < 4:
            return
        mode = parts[1]
        p_label = parts[2]
        v = int(parts[3])
        if mode == "d":
            if p_label == "p0":
                pins.digital_write_pin(DigitalPin.P0, v)
            elif p_label == "p1":
                pins.digital_write_pin(DigitalPin.P1, v)
            elif p_label == "p2":
                pins.digital_write_pin(DigitalPin.P2, v)
        elif p_label == "p0":
            pins.analog_write_pin(AnalogPin.P0, v)
        elif p_label == "p1":
            pins.analog_write_pin(AnalogPin.P1, v)
        elif p_label == "p2":
            pins.analog_write_pin(AnalogPin.P2, v)
    elif cmd == "tone":
        # --- MUSIC / TONE ---
        if len(parts) < 3:
            return
        freq = int(parts[1])
        dur = int(parts[2])
        music.play(music.create_sound_expression(WaveShape.SAWTOOTH,
                freq,
                freq,
                255,
                255,
                dur,
                SoundExpressionEffect.NONE,
                InterpolationCurve.LINEAR),
            music.PlaybackMode.UNTIL_DONE)
    elif cmd == "print":
        # --- LED MATRIX COMMANDS ---
        text = ""
        for i in range(1, len(parts)):
            text += parts[i] + " "
        basic.show_string("" + (text.trim()))
    elif cmd == "plot":
        if len(parts) < 3:
            return
        led.plot(int(parts[1]), int(parts[2]))
    elif cmd == "unplot":
        if len(parts) < 3:
            return
        led.unplot(int(parts[1]), int(parts[2]))
    elif cmd == "toggle":
        if len(parts) < 3:
            return
        led.toggle(int(parts[1]), int(parts[2]))
    elif cmd == "clear":
        # --- SYSTEM COMMANDS ---
        basic.clear_screen()
    elif cmd == "reset":
        basic.clear_screen()
        pins.analog_write_pin(AnalogPin.P0, 0)
        pins.analog_write_pin(AnalogPin.P1, 0)
        pins.analog_write_pin(AnalogPin.P2, 0)
        music.stop_all_sounds()
        reply("RESET_OK")
    elif cmd == "ping":
        reply("pong")
cmd = ""
bluetooth.start_uart_service()
basic.show_icon(IconNames.SMALL_DIAMOND)