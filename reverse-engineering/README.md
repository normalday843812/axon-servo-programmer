# How the Axon MK2 programmer was decoded

This folder records how the USB protocol in [`../PROTOCOL.md`](../PROTOCOL.md)
was worked out, and keeps the scripts that were used. It was done in November
2026 on a Mac, without ever running the official app.

Nothing here is needed to *use* the tool.

## What was done

1. **Looked at the USB device.** The programmer enumerates as a vendor-defined
   HID device (VID 0x0473 / PID 0x13AA, "USBBootloaderV1.4", "AGF STM32 FNS")
   with 64-byte reports, so an ordinary HID library can talk to it with no
   driver.
2. **Checked prior work.** [DevMello/AxonProgrammer](https://github.com/DevMello/AxonProgrammer)
   targets the older MK1 programmer (VID 0x0471) and detects whether a servo is
   plugged in, which confirmed the general packet shape.
3. **Decompiled the official app.** `Axon_Software_MK2_v1.1.2.exe` is a .NET
   WinForms program obfuscated with Dotfuscator.
   - [de4dot](https://github.com/kant2002/de4dot) removed the obfuscation
     (names, encrypted strings, scrambled control flow).
   - [ILSpy](https://github.com/icsharpcode/ILSpy)'s `ilspycmd` turned the
     result into readable C#.
   - The main window class is `AGF`. The methods that matter:
     `timer_1_Tick` (find the adapter), `timer_0_Tick` (status), `method_14`
     (detect servo), `method_13` (read), `method_15` and `btnWrite_Click`
     (write), `method_16` (settings layout), `btnDefault_Click`,
     `btnUPF_Click` and `method_23` (firmware update), `checkPPMOut_MouseClick`
     and `method_12` (signal output). `GClass4` holds the AES routine for
     firmware files. (These are de4dot's generated names for v1.1.2.)
   - The older `Axon_Servo_Programming_Software_v1.0.5.exe` is a native program
     for the MK1 programmer and was not analysed.
4. **Decrypted the firmware files** (AES-128-CBC) into their text form: page
   erase commands plus Intel HEX records.
5. **Confirmed everything on real hardware** with a MAX MK2 servo, starting
   with read-only commands, then reversible writes, then a full firmware flash.
6. **Found and fixed a programmer freeze.** Talking to the servo's bootloader
   froze the programmer until it was replugged. The cause was that the joystick
   signal was still on; the official app switches the signal off first (in
   `btnUPF_Click`, `checkPPMOut` counts joystick mode as "on"). Details are in
   `../PROTOCOL.md`.

## What is in this folder

| Path | What it is |
| --- | --- |
| `scripts/probe.py` | The first read-only probe of the programmer |
| `scripts/flash_sim.py` | Runs the tool's flash routine against a simulated bootloader and compares every packet with a direct port of the official app's loop. Needs real `.sfm` files as arguments |
| `scripts/bootlab.py` | Helper for raw, timestamped packet experiments |
| `scripts/exp1_exit_then_powercycle.py` | Bootloader experiment that reproduces the freeze (erases nothing) |
| `scripts/exp2_signal_off_first.py` | The corrected sequence that works (erases nothing) |
| `scripts/hexinfo.py`, `scripts/fwid.py` | Inspect a decrypted firmware image |
| `scripts/resx_extract.py`, `scripts/u16strings.py` | Pull images and strings out of the app |
| `redo.sh` | Re-runs deobfuscation and decompilation on an app `.exe` |

## What is deliberately not in this repository

- Axon's apps and firmware files. Get them from Axon.
- The decompiled source of Axon's app, the decrypted firmware, and the app's
  artwork. They are Axon's copyrighted work. `redo.sh` regenerates the source
  from your own copy of the app.
- The toolchain binaries (about 170 MB).

`.gitignore` keeps all of these out if you work in a clone.

## Redoing it (for example, when Axon releases a new app version)

`redo.sh` expects a `toolchain/` folder here containing:

| Folder | How to get it |
| --- | --- |
| `toolchain/dotnet/` | The .NET 8 SDK or runtime: `dotnet-install.sh --channel 8.0 --install-dir toolchain/dotnet` (script from https://dot.net/v1/dotnet-install.sh) |
| `toolchain/ilspycmd/` | `dotnet tool install ilspycmd --version 9.1.0.7988 --tool-path toolchain/ilspycmd` |
| `toolchain/de4dot/` | Build https://github.com/kant2002/de4dot at tag `v3.2.0`: `dotnet publish de4dot/de4dot.csproj -c Release -f net8.0 -o toolchain/de4dot` |

Then:

```
./redo.sh /path/to/Axon_Software_MK2_vX.exe ./new-version
```

and read `./new-version/source/AGF.cs`.

The Python scripts import the tool from the repository root, so run them with
a Python that has `hidapi` installed, for example:

```
python3 scripts/flash_sim.py /path/to/Axon_MAX_MK2_Servo_Mode.sfm
python3 scripts/exp2_signal_off_first.py
```
