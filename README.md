# axon: command-line tool for the Axon Servo Programmer MK2

[![Build](https://github.com/normalday843812/axon-servo-programmer/actions/workflows/build.yml/badge.svg)](https://github.com/normalday843812/axon-servo-programmer/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/normalday843812/axon-servo-programmer)](https://github.com/normalday843812/axon-servo-programmer/releases/latest)
[![License](https://img.shields.io/github/license/normalday843812/axon-servo-programmer)](LICENSE)

Programs Axon MK2 servos through the Axon Servo Programmer MK2 (the one with
the joystick). Runs on macOS and should run on Linux.

It talks to the programmer directly over USB, so there are no drivers to
install. You can read and change every servo setting, save and load
configurations, factory-reset a servo, test it, and switch it between Servo
mode and Continuous Rotation (CR) mode.

This is an unofficial project. It is not made by, endorsed by, or affiliated
with Axon Robotics. It can rewrite your servo's settings and firmware, so use
it at your own risk.

```
$ axon
Adapter   Axon Programmer MK2 (USBBootloaderV1.4)   4.86 V   0.00 A   servo power on   signal source: joystick (1500 us)
Servo     MAXMK2   firmware AISV112208   mode: Servo (positional)   made 2025-08-20

  setting      value                                 allowed
  left         250                                   10..255  (factory 250)
  right        250                                   10..255  (factory 250)
  neutral      0                                     -25..25
  damping      120                                   1..255
  power        100.0%                                10..100 %
  sensitivity  ultra-high                            ultra-high | high | medium | low
  inversion    off                                   on | off
  ...
```

## Requirements

- An Axon Servo Programmer MK2 (USB ID `0473:13aa`) and an Axon MK2 servo
  (MAX or MINI).
- macOS. Linux and Windows should work because the USB library supports them,
  but they have not been tried. See [Troubleshooting](#troubleshooting).
- Python 3.9 or newer, only if you install from source instead of downloading
  the ready-made program.

The older MK1 programmer (USB ID `0471:13aa`) uses a different protocol and is
not supported.

## Install

### Download a release

Each [release](https://github.com/normalday843812/axon-servo-programmer/releases/latest)
has a standalone program for each kind of computer. Python does not have to be
installed to use these.

| Computer | File |
| --- | --- |
| Mac with Apple Silicon (M1 or later) | `axon-macos-arm64` |
| Mac with an Intel processor | `axon-macos-x86_64` |
| Linux, x86_64 | `axon-linux-x86_64` |
| Linux, ARM64 | `axon-linux-aarch64` |
| Windows | `axon-windows-x86_64.exe` |

On macOS or Linux, download it from a terminal:

```
curl -L -o axon https://github.com/normalday843812/axon-servo-programmer/releases/latest/download/axon-macos-arm64
chmod +x axon
./axon
```

Replace `axon-macos-arm64` with the file for your computer. To run it from any
folder, move it onto your PATH:

```
sudo mkdir -p /usr/local/bin && sudo mv axon /usr/local/bin/
```

If you download the file with a browser on macOS instead, macOS will refuse to
run it until you clear the download flag once:
`xattr -d com.apple.quarantine axon`.

On Windows, download `axon-windows-x86_64.exe` from the release page and run it
from PowerShell or Command Prompt. Windows may show a warning because the file
is not signed.

`SHA256SUMS.txt` in each release lists the checksum of every file.

### Install from source

Download or clone this repository, then from inside its folder:

```
python3 -m pip install .
```

That installs an `axon` command. To keep it separate from your other Python
packages, use [pipx](https://pipx.pypa.io) (`pipx install .`) or a virtual
environment:

```
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/axon
```

## Usage

Plug the programmer into your computer, plug a servo into the programmer, and run:

| Command | What it does |
| --- | --- |
| `axon` | Show the programmer, the connected servo and every setting |
| `axon set left=120 right=120` | Change one or more settings |
| `axon set inversion=on` | Reverse the servo's direction |
| `axon save my-servo.svp` | Save all settings to a file |
| `axon load my-servo.svp` | Apply the settings from a file |
| `axon default` | Reset the settings to factory defaults |
| `axon flash FILE.sfm` | Load firmware (switches between Servo mode and CR mode) |
| `axon pulse 1500` | Drive the servo from the computer (500 to 2500 us) |
| `axon pulse joystick` | Give control back to the programmer's joystick |
| `axon pulse off` | Stop the signal output |
| `axon monitor` | Live voltage, current and pulse readout (Ctrl-C to stop) |

Every change is read back from the servo to confirm it was stored. The previous
settings are saved to `~/axon-backups/` first, so a change can be undone:

```
axon load ~/axon-backups/MAXMK2-20261119-201211-before.svp
```

`.svp` files use the same format as the Save and Open buttons in the official app.
Add `-v` (for example `axon -v set left=120`) to see the raw USB packets.

## Settings

| Setting | Values | Notes |
| --- | --- | --- |
| `left`, `right` | 10 to 255 | Travel on each side of neutral ("L" and "R" in the official app). Factory is 250 |
| `neutral` | -25 to 25 | Center trim |
| `damping` | 1 to 255 | Damping Factor |
| `power` | 10 to 100 (%) | PWM Power |
| `sensitivity` | `ultra-high`, `high`, `medium`, `low` | |
| `inversion` | `on`, `off` | Reverse direction |
| `soft-start` | 1 to 11 | Soft Start level |
| `lose-ppm` | `release`, `keep`, `neutral` | What the servo does when the signal is lost |
| `ol1-level`, `ol2-level`, `ol3-level` | 10 to 100 (%) | Over Load Protection power steps |
| `ol1-time`, `ol2-time`, `ol3-time` | 0 to 10.5 (s) | When each step starts |
| `signal` | `normal`, `sanwa-sr`, `futaba-sr`, `futaba-ur` | RC radio high-speed modes. Leave on `normal` for FTC |
| `beep` | `on`, `off` | |
| `name` | up to 12 characters | A label stored in the servo |

A servo running CR firmware only has `power`, `inversion`, `proptl` (0.1 to 25 s)
and `beep`. These are the same four the official app shows.

Two hidden factory tuning values (`min-power`, `sys-amp`) are listed by
`axon info --advanced` and can only be changed with `axon set --advanced ...`.

## Switching between Servo mode and CR mode

The mode is set by the firmware on the servo. Download the firmware (`.sfm`)
files from Axon. They are linked on the
[Axon Servo Programmer MK2 product page](https://www.gobilda.com/axon-servo-programmer-mk2/).
Then:

```
axon flash Axon_MAX_MK2_CR_Mode.sfm        # MAX to continuous rotation
axon flash Axon_MAX_MK2_Servo_Mode.sfm     # MAX to normal servo
```

Use the `MINI` files for a MINI MK2. The command asks for confirmation, takes
about 30 seconds, and prints the servo's new settings when it finishes.

- Flashing resets every setting to that firmware's defaults, as the official
  app does. The old settings are saved to `~/axon-backups/` first, and
  `axon load` restores them.
- While it runs, do not unplug anything and do not touch the programmer's
  joystick or buttons.
- A firmware file for the wrong model (MAX or MINI) is refused before anything
  is erased.
- `axon flash FILE.sfm --dry-run` checks a file without sending anything.
- If a flash is interrupted, leave everything plugged in and run
  `axon flash FILE.sfm --recover`.

This repository contains no Axon software or firmware.

## What has been tested

Tested on a real programmer with a MAX MK2 servo, on macOS:

| Feature | Status |
| --- | --- |
| Read, set, save, load, factory default | Works. Settings survive a power cycle |
| Signal output (`pulse`), joystick hand-back, `monitor` | Works |
| Flashing the MAX MK2 Servo-mode firmware | Works. All 411 packets accepted on the first attempt |
| Flashing a CR-mode firmware | Same code path, and the files parse correctly, but not yet run on a real servo |
| CR-mode settings (`proptl` and the others) | Taken from the official app's code, not yet run on a real servo |
| MINI MK2 | Not tried |
| Linux, Windows | Not tried |
| Release downloads | Built automatically. Each one passes the unit tests and starts correctly on its platform, but none has been run with a programmer attached yet |

If you try one of the untested rows, please open a
[hardware report](https://github.com/normalday843812/axon-servo-programmer/issues/new/choose) with the result.

## Troubleshooting

- "Axon MK2 programmer not found": check the USB cable, and that it is the MK2
  programmer.
- "did not identify", or no reply at all: the programmer's own firmware can
  lock up. Unplug its USB cable for a few seconds and plug it back in. The
  servo is not affected.
- "no servo detected": check which way round the servo plug is in the programmer.
- Linux: you will probably need a udev rule to open the device without `sudo`.
  Put this in `/etc/udev/rules.d/99-axon.rules`, run
  `sudo udevadm control --reload && sudo udevadm trigger`, and replug:

  ```
  SUBSYSTEM=="usb", ATTRS{idVendor}=="0473", ATTRS{idProduct}=="13aa", MODE="0666"
  KERNEL=="hidraw*", ATTRS{idVendor}=="0473", ATTRS{idProduct}=="13aa", MODE="0666"
  ```

## How it works

[PROTOCOL.md](PROTOCOL.md) documents the USB protocol: the packet format, every
command, the layout of the servo's settings block, the firmware file format,
and the firmware update sequence.

[reverse-engineering/](reverse-engineering/) describes how the protocol was
worked out and contains the scripts that were used.

The tests run without a programmer or servo:

```
python3 -m unittest discover -s tests
```

The release downloads are built by GitHub Actions
([.github/workflows/build.yml](.github/workflows/build.yml)) with PyInstaller.
To build one yourself:

```
python3 -m pip install . pyinstaller
python3 -m PyInstaller --onefile --name axon axon.py
```

The program is written to `dist/axon`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes between versions are listed in
[CHANGELOG.md](CHANGELOG.md).

## Credits

- [DevMello/AxonProgrammer](https://github.com/DevMello/AxonProgrammer): an
  earlier project for the MK1 programmer.
- [de4dot](https://github.com/kant2002/de4dot) and
  [ILSpy](https://github.com/icsharpcode/ILSpy): used to read the official app.
- [hidapi](https://github.com/trezor/cython-hidapi): the USB HID library.

## License

MIT. See [LICENSE](LICENSE). "Axon" is a trademark of its owner and is used
here only to identify the hardware this tool works with.
