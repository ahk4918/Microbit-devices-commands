const FW_VERSION = "2026.01.4"
const FW_TYPE = "V1-MINIMAL"
const DEVICE_TYPE = "microbit-v1"

// ---------- Reply helpers ----------
function reply(msg: string) {
    serial.writeLine(msg)
}

function dbg(msg: string) {
    // V1 has tiny RAM — keep debug minimal and optional
    // Uncomment if needed:
    // serial.writeLine("[DBG] " + msg)
}

// ---------- Command processor ----------
function process_command(raw: string) {
    let msg = raw.trim().toLowerCase()
    if (msg.length == 0) return

    let parts = msg.split(" ")
    let cmd = parts[0]

    // ----- Sensors -----
    if (cmd == "get_sensor") {
        if (parts.length < 2) return
        let t = parts[1]

        if (t == "temp") {
            reply("" + input.temperature())
        }
        else if (t == "light") {
            reply("" + input.lightLevel())
        }
        else {
            reply("ERR")
        }
        return
    }

    // ----- Pin read -----
    if (cmd == "get_pin") {
        if (parts.length < 2) return
        let p = parts[1]
        let v = 0

        if (p == "p0") v = pins.analogReadPin(AnalogPin.P0)
        else if (p == "p1") v = pins.analogReadPin(AnalogPin.P1)
        else if (p == "p2") v = pins.analogReadPin(AnalogPin.P2)
        else {
            reply("ERR")
            return
        }

        reply("PIN " + p + ": " + v)
        return
    }

    // ----- Pin write -----
    if (cmd == "pin") {
        if (parts.length < 4) return
        let mode = parts[1]
        let p = parts[2]
        let v = parseInt(parts[3])

        if (mode == "d") {
            if (p == "p0") pins.digitalWritePin(DigitalPin.P0, v)
            else if (p == "p1") pins.digitalWritePin(DigitalPin.P1, v)
            else if (p == "p2") pins.digitalWritePin(DigitalPin.P2, v)
        } else {
            if (p == "p0") pins.analogWritePin(AnalogPin.P0, v)
            else if (p == "p1") pins.analogWritePin(AnalogPin.P1, v)
            else if (p == "p2") pins.analogWritePin(AnalogPin.P2, v)
        }
        return
    }

    // ----- Text -----
    if (cmd == "print") {
        if (parts.length < 2) return
        let text = ""
        for (let i = 1; i < parts.length; i++) text += parts[i] + " "
        basic.showString(text.trim())
        return
    }

    // ----- LED matrix -----
    if (cmd == "plot") {
        led.plot(parseInt(parts[1]), parseInt(parts[2]))
        return
    }
    if (cmd == "unplot") {
        led.unplot(parseInt(parts[1]), parseInt(parts[2]))
        return
    }
    if (cmd == "toggle") {
        led.toggle(parseInt(parts[1]), parseInt(parts[2]))
        return
    }
    if (cmd == "clear") {
        basic.clearScreen()
        return
    }

    // ----- System -----
    if (cmd == "reset") {
        basic.clearScreen()
        pins.analogWritePin(AnalogPin.P0, 0)
        pins.analogWritePin(AnalogPin.P1, 0)
        pins.analogWritePin(AnalogPin.P2, 0)
        reply("RESET_OK")
        return
    }

    if (cmd == "ping") {
        reply("pong")
        return
    }

    if (cmd == "version") {
        reply("Version: " + FW_VERSION)
        reply("Type: " + FW_TYPE)
        reply("Device Type: " + DEVICE_TYPE)
        return
    }

    if (cmd == "status") {
        reply("Status: OK")
        reply("Version: " + FW_VERSION)
        reply("Type: " + FW_TYPE)
        reply("Device Type: " + DEVICE_TYPE)
        reply("Sensors: temp light")
        reply("Pins: p0 p1 p2")
        reply("Transport: usb")
        return
    }
}

// ---------- Serial handlers ----------
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), () => {
    let line = serial.readLine()
    process_command(line)
})

// ---------- Startup ----------
serial.setBaudRate(BaudRate.BaudRate115200)
basic.showIcon(IconNames.SmallDiamond)
