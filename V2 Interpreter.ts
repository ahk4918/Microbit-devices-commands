// ===============================
// micro:bit V2 Interpreter
// USB + (optional) BLE UART
// ===============================

const FW_VERSION = "2026.03.1"
const FW_TYPE = "V2-STANDARD"
const DEVICE_TYPE = "microbit-v2"

// ---------- CONFIG ----------
const ENABLE_BLE = true   // set false if you want USB-only

// ---------- REPLY HELPERS ----------
function reply(msg: string) {
    serial.writeLine(msg)
}

function dbg(msg: string) {
    // Uncomment if you want on-device debug
    // serial.writeLine("[DBG] " + msg)
}

// ---------- BLE UART ----------
let bleRxBuf = ""
if (ENABLE_BLE) {
    bluetooth.startUartService()
    bluetooth.onUartDataReceived("\n", () => {
        let line = bluetooth.uartReadUntil("\n")
        process_command(line)
    })
}

// ---------- CORE COMMAND PROCESSOR ----------
function process_command(raw: string) {
    let msg = raw.trim()
    if (msg.length == 0) return

    dbg("CMD: " + msg)

    let lower = msg.toLowerCase()
    let parts = lower.split(" ")
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
        else if (t == "accel") {
            reply(
                input.acceleration(Dimension.X) + "," +
                input.acceleration(Dimension.Y) + "," +
                input.acceleration(Dimension.Z)
            )
        }
        else if (t == "compass") {
            reply("" + input.compassHeading())
        }
        else if (t == "sound") {
            // V2 only
            reply("" + input.soundLevel())
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
        else if (p == "p8") v = pins.analogReadPin(AnalogPin.P8)
        else if (p == "p16") v = pins.analogReadPin(AnalogPin.P16)
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

        let dp: DigitalPin = null
        let ap: AnalogPin = null

        if (p == "p0") { dp = DigitalPin.P0; ap = AnalogPin.P0 }
        else if (p == "p1") { dp = DigitalPin.P1; ap = AnalogPin.P1 }
        else if (p == "p2") { dp = DigitalPin.P2; ap = AnalogPin.P2 }
        else if (p == "p8") { dp = DigitalPin.P8; ap = AnalogPin.P8 }
        else if (p == "p16") { dp = DigitalPin.P16; ap = AnalogPin.P16 }
        else {
            reply("ERR")
            return
        }

        if (mode == "d") {
            pins.digitalWritePin(dp, v)
        } else {
            pins.analogWritePin(ap, v)
        }
        return
    }

    // ----- Text -----
    if (cmd == "print") {
        if (parts.length < 2) return
        let text = msg.substr(msg.indexOf(" ") + 1)
        basic.showString(text)
        return
    }

    // ----- LED matrix -----
    if (cmd == "plot") {
        if (parts.length < 3) return
        led.plot(parseInt(parts[1]), parseInt(parts[2]))
        return
    }
    if (cmd == "unplot") {
        if (parts.length < 3) return
        led.unplot(parseInt(parts[1]), parseInt(parts[2]))
        return
    }
    if (cmd == "toggle") {
        if (parts.length < 3) return
        led.toggle(parseInt(parts[1]), parseInt(parts[2]))
        return
    }
    if (cmd == "clear") {
        basic.clearScreen()
        return
    }

    // ----- Simple tone (V2 only) -----
    if (cmd == "tone") {
        if (parts.length < 3) return
        let freq = parseInt(parts[1])
        let ms = parseInt(parts[2])
        music.playTone(freq, ms)
        return
    }

    // ----- System -----
    if (cmd == "reset") {
        basic.clearScreen()
        pins.analogWritePin(AnalogPin.P0, 0)
        pins.analogWritePin(AnalogPin.P1, 0)
        pins.analogWritePin(AnalogPin.P2, 0)
        pins.analogWritePin(AnalogPin.P8, 0)
        pins.analogWritePin(AnalogPin.P16, 0)
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
        reply("Sensors: temp light accel compass sound")
        reply("Pins: p0 p1 p2 p8 p16")
        reply("Transport: " + (ENABLE_BLE ? "usb+ble" : "usb"))
        return
    }
        // ----- Help -----
    if (cmd == "help") {
        reply("Commands:");
        reply("  ping                - Check connection");
        reply("  version             - Show firmware version");
        reply("  status              - Show device status");
        reply("  reset               - Reset pins + clear screen");
        reply("  get_sensor <type>   - temp | light | accel | compass | sound");
        reply("  get_pin <pin>       - p0 p1 p2 p8 p16");
        reply("  pin <d/a> <pin> <v> - Digital/analog write");
        reply("  print <text>        - Scroll text");
        reply("  plot x y            - LED on");
        reply("  unplot x y          - LED off");
        reply("  toggle x y          - LED toggle");
        reply("  clear               - Clear LED matrix");
        reply("  tone <freq> <ms>    - Play tone (V2)");
        reply("  help                - Show this help");
        return;
    }

}

// ---------- SERIAL HANDLER ----------
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), () => {
    let line = serial.readLine()
    process_command(line)
})

// ---------- STARTUP ----------
serial.setBaudRate(BaudRate.BaudRate115200)
basic.showIcon(IconNames.SmallDiamond)
