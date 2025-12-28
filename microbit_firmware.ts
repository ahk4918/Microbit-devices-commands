//  Version 2026.01.1
//  Micro:bit device commands over Serial and Bluetooth UART
let cmd = ""

function reply(msg: string) {
    bluetooth.uartWriteLine(msg)
    serial.writeLine(msg)
}

//  Initialization
bluetooth.onUartDataReceived(serial.delimiters(Delimiters.NewLine), function on_uart_data_received() {
    process_command(bluetooth.uartReadUntil(serial.delimiters(Delimiters.NewLine)))
})
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function on_data_received() {
    process_command(serial.readLine())
})
function process_command(msg_input: string) {
    let _type: string;
    let p_name: string;
    let val: number;
    let mode: string;
    let p_label: string;
    let v: number;
    let freq: number;
    let dur: number;
    let text: string;
    
    let raw_msg = msg_input.trim().toLowerCase()
    if (raw_msg.length == 0) {
        return
    }
    
    let parts = _py.py_string_split(raw_msg, " ")
    //  FIX: Get the first element (string) from the list
    cmd = parts[0]
    //  --- SENSOR COMMANDS ---
    if (cmd == "get_sensor") {
        if (parts.length < 2) {
            return
        }
        
        _type = parts[1]
        if (_type == "temp") {
            reply("" + ("" + input.temperature()))
        } else if (_type == "light") {
            reply("" + ("" + input.lightLevel()))
        } else if (_type == "accel") {
            reply("" + ("" + input.acceleration(Dimension.Strength)))
        } else if (_type == "compass") {
            reply("" + ("" + input.compassHeading()))
        }
        
    } else if (cmd == "get_pin") {
        //  --- PIN COMMANDS ---
        if (parts.length < 2) {
            return
        }
        
        p_name = parts[1]
        val = 0
        if (p_name == "p0") {
            val = pins.analogReadPin(AnalogPin.P0)
        } else if (p_name == "p1") {
            val = pins.analogReadPin(AnalogPin.P1)
        } else if (p_name == "p2") {
            val = pins.analogReadPin(AnalogPin.P2)
        }
        
        reply("PIN " + p_name + ": " + ("" + ("" + val)))
    } else if (cmd == "pin") {
        if (parts.length < 4) {
            return
        }
        
        mode = parts[1]
        p_label = parts[2]
        v = parseInt(parts[3])
        if (mode == "d") {
            if (p_label == "p0") {
                pins.digitalWritePin(DigitalPin.P0, v)
            } else if (p_label == "p1") {
                pins.digitalWritePin(DigitalPin.P1, v)
            } else if (p_label == "p2") {
                pins.digitalWritePin(DigitalPin.P2, v)
            }
            
        } else if (p_label == "p0") {
            pins.analogWritePin(AnalogPin.P0, v)
        } else if (p_label == "p1") {
            pins.analogWritePin(AnalogPin.P1, v)
        } else if (p_label == "p2") {
            pins.analogWritePin(AnalogPin.P2, v)
        }
        
    } else if (cmd == "tone") {
        //  --- MUSIC / TONE ---
        if (parts.length < 3) {
            return
        }
        
        freq = parseInt(parts[1])
        dur = parseInt(parts[2])
        music.play(music.createSoundExpression(WaveShape.Sawtooth, freq, freq, 255, 255, dur, SoundExpressionEffect.None, InterpolationCurve.Linear), music.PlaybackMode.UntilDone)
    } else if (cmd == "print") {
        //  --- LED MATRIX COMMANDS ---
        text = ""
        for (let i = 1; i < parts.length; i++) {
            text += parts[i] + " "
        }
        basic.showString("" + text.trim())
    } else if (cmd == "plot") {
        if (parts.length < 3) {
            return
        }
        
        led.plot(parseInt(parts[1]), parseInt(parts[2]))
    } else if (cmd == "unplot") {
        if (parts.length < 3) {
            return
        }
        
        led.unplot(parseInt(parts[1]), parseInt(parts[2]))
    } else if (cmd == "toggle") {
        if (parts.length < 3) {
            return
        }
        
        led.toggle(parseInt(parts[1]), parseInt(parts[2]))
    } else if (cmd == "clear") {
        //  --- SYSTEM COMMANDS ---
        basic.clearScreen()
    } else if (cmd == "reset") {
        basic.clearScreen()
        pins.analogWritePin(AnalogPin.P0, 0)
        pins.analogWritePin(AnalogPin.P1, 0)
        pins.analogWritePin(AnalogPin.P2, 0)
        music.stopAllSounds()
        reply("RESET_OK")
    } else if (cmd == "ping") {
        reply("pong")
    } else if (cmd == "version") {
        reply("microbit_V2026.01.1")
    }
    
}

bluetooth.startUartService()
basic.showIcon(IconNames.SmallDiamond)
