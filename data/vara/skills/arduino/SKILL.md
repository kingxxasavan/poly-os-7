---
name: arduino
description: Write, compile and upload Arduino, ESP32 and other microcontroller sketches with arduino-cli
---

# Arduino with arduino-cli

## Set up (once; installing needs approval)

arduino-cli isn't a Debian package. With the person's OK, install Arduino's official build into
`~/.local/bin` (no admin rights needed):
`curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=~/.local/bin sh`.
The Arduino IDE (PolyMarket, on PCs) is the graphical alternative.

```bash
arduino-cli config init                 # skip if ~/.arduino15/arduino-cli.yaml exists
arduino-cli core update-index
arduino-cli core install arduino:avr    # Uno, Nano, Mega
```

ESP32: add `https://espressif.github.io/arduino-esp32/package_esp32_index.json` with
`arduino-cli config add board_manager.additional_urls <url>`, update the index, `core install esp32:esp32`.

## Find the board

`arduino-cli board list` shows the port (`/dev/ttyACM0`, `/dev/ttyUSB0`) and, for known boards,
the FQBN (`arduino:avr:uno`). Clones with a CH340 chip show no FQBN: ask which board it is, then
`remember` it. "Permission denied" on the port: the person must be in the `dialout` group
(`sudo usermod -aG dialout $USER`, then sign out and in); they run that themselves.

## Sketch, compile, upload

```bash
arduino-cli sketch new ~/Projects/blink          # makes blink/blink.ino
arduino-cli compile --fqbn arduino:avr:uno ~/Projects/blink
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno ~/Projects/blink
```

- Libraries: `arduino-cli lib search servo`, `arduino-cli lib install Servo`.
- Uploading changes what the board does: say what the new sketch does (pins, motors) first.
- Read serial output for a few seconds: `stty -F /dev/ttyACM0 9600 raw -echo && timeout 10 cat /dev/ttyACM0`
  (with run_command; match the baud rate in `Serial.begin`).
