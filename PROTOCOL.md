# Axon Servo Programmer MK2: USB protocol

Worked out from *Axon Software MK2 v1.1.2* (a .NET app, deobfuscated with
de4dot and decompiled with ILSpy) and confirmed against a real programmer with
a MAX MK2 servo. Items marked *(unverified)* come from the decompiled code only.

## Transport

- USB HID, **VID 0x0473 / PID 0x13AA**, product string `USBBootloaderV1.4`,
  manufacturer `AGF STM32 FNS`. Vendor usage page 0xFF00.
  (VID 0x0472 is the programmer's own firmware-update mode. It is not used here.)
- Every message is a 64-byte report with **report ID 0x04**. Host sends an
  output report, device answers with one input report.
- Request: `04 <cmd> <args...>`, zero padded.
- Reply: `04 <status> .. .. <echo> <data...>`. `status` 0x01 = OK.
  `reply[4]` echoes the command (or the length, for read/write), which the
  official app uses to skip stale replies.

## Adapter commands

| Cmd | Request | Reply / meaning |
| --- | --- | --- |
| `91` | `04 91` | Identify. `reply[5] == 0x22` for a valid MK2 programmer |
| `AF` | `04 AF` | Status (see below) |
| `B0` | `04 B0 00 <1/0>` | Servo power on / off |
| `AA` | `04 AA 00 <n>` | Signal source: 1 = USB, 2 = joystick, 3 = external receiver |
| `AC` | `04 AC 00 <period> <pulse> <max> <min> <center> <period>` | Start USB pulse output (all 16-bit big-endian, us). period = pulse = 0 stops it |
| `AB` | `04 AB 00 00 00 <pulse>` | Set the USB pulse width (us, big-endian) |
| `A9` | `04 A9 <81/00> <speed>` | Auto sweep on/off *(unverified)* |
| `AD` | `04 AD 0F 32 64 96 ...` | "Slow return" test *(unverified)* |
| `B1` | `04 B1` | Reboot the **programmer** into its own updater. Do not send. |

Status reply (`AF`), big-endian fields:

| Bytes | Meaning |
| --- | --- |
| 5-6 | Current output pulse (us) |
| 9-10 | Input voltage: `raw / 4096 * 3.3 * 5.99` V |
| 13-14 | Servo current: `raw / 4096 * 3.3 / 0.6` A |
| 15 | Signal source: 0 none, 1 USB, 2 joystick, 3 external |
| 16 | Servo power: 3 = on, 2 = off |
| 19 | 1 = a signal is present on PPM IN |
| 20-21, 22-23 | PPM IN period and pulse width (us) |

## Servo commands (relayed by the programmer)

| Cmd | Request | Reply / meaning |
| --- | --- | --- |
| `8A` | `04 8A 00 00 04` | Detect servo. `reply[1] == 1`, data `34 tt 22 vv`. Firmware label = `AISV<tt>22<vv>`. `tt` of 0x41/0x31 = the reduced "CR" parameter set *(mapping to CR mode inferred, not yet seen on hardware)*. No servo / servo unpowered: `04 FA 00 22 8A` |
| `CD` | `04 CD <addr hi> <addr lo> <len>` | Read `len` (at most 59) parameter bytes; data starts at `reply[5]` |
| `CB` | `04 CB <addr hi> <addr lo> <len> <data>` | Write parameter bytes. The official Write sends addr 0, len 44. Reply echoes the data |
| `5A` | `04 5A 00 00 01` | Factory default. `reply[5] == 0xAA` = done |

Writes are stored permanently (checked across a servo power cycle).

Observed: after `5A`, parameter byte 25 reads `01` (it is `00` from the
factory image). It is not one of the named settings; purpose unknown.

## Parameter block (59 bytes)

| Offset | Setting | Encoding |
| --- | --- | --- |
| 0 | SysAmp (hidden) | 6-255 |
| 1 | Damping Factor | 1-255 |
| 2 | Sensitivity | 25 ultra-high, 50 high, 100 medium, 150 low |
| 6 | PWM Power | 25-255 = percent * 2.55 |
| 7 | MinPower (hidden) | 1-255 |
| 8 | R range | 10-255 (factory 250) |
| 9 | L range | 10-255 (factory 250) |
| 10 | Soft Start | 1-10 = level, 0xFF = level 11 |
| 12, 13, 14 | Over Load level 1, 2, 3 | percent * 2.55 |
| 15, 16, 17 | Over Load time 1, 2, 3 | seconds / 0.077. In CR mode byte 15 is ProPTL, seconds / 0.1 |
| 18 | Signal-mode constant | 220 = SANWA SR, 143 = Futaba UR (used when flag bit 7 is set) |
| 20 | Flags | bit0 inversion, bit4 Futaba SR, bit7 SANWA/UR, bit6 lose-PPM "keep", bit6+bit3 lose-PPM "go neutral" |
| 22-23 | Neutral | int16 little-endian, -25 to 25 |
| 26 | Flags 2 | bit0 beep |
| 32-43 | User name | ASCII, padded with `*` |
| 44, 45, 46 | Manufacture day, month, year minus 2000 | read-only |
| 47-58 | Model name (`MAXMK2`, `MINIMK2`) | ASCII, padded with `*`, read-only |

Other bytes are not exposed by the official app and are left untouched.
In flash the block lives at 0x1C01 to 0x1C3B (0x1C00 holds `5A`).

`.svp` settings files are 95 bytes: the 59-byte block, zero padding, then
`56 34` ("V4") at offsets 93-94.

## Firmware files (`.sfm`)

- Skip the first 16 bytes; the rest is **AES-128-CBC**, no padding,
  key `77 0B AC D9 28 01 CE 8A 30 2D A2 10 CD 24 8D 1F`, IV all zero.
- Plaintext is text lines:
  - `@<id1><id2><model>`: header, for example `@0822MAXMK2`
  - `$<hh><ll>`: erase the 512-byte page at that address (0x0400 to 0x1C00)
  - `:...`: standard Intel HEX records (16-bit addresses, 0x0400 to 0x1C5F)
- The image includes the parameter block, so flashing resets all settings.
- Build tags seen at 0x1AF0: `ASSV32 07/07/25` (Servo mode), `ASSV34 08/06/25` (CR mode).

## Firmware update sequence

0. **Switch the programmer's signal output off first** (`04 AC 00 00 00 00 00 <max> <min>
   <center> <period>`, status then shows source 0). The official app does this whenever the
   source is USB, joystick or receiver. From here until step 4, send nothing but
   `80` to `83`: no `AF` status and no `8A` detect (the official app stops both timers).
1. `04 80 04 01 02 03 04` -> `reply[5..8]` = bootloader version (`V...`),
   `reply[9], reply[10]` must equal `id1, id2` from the file header.
   The file's model must equal the servo's model name. Takes ~200 ms.
2. `04 81 16 <22 random bytes>` -> `seed[i] = random[i] XOR reply[5+i]`.
   (`reply[3..4]` echo the first two random bytes. If `reply[3..24]` is a plain echo of
   all 22, the bootloader never answered.)
3. For each line, send `04 82 16 <body>` with packet bytes 3-24 XORed with the seed
   (rest of the packet is random filler):
   - erase: body `0A <hh> <ll>` -> `reply[5] == 0x55`
   - write: body `3A <hex record bytes>` -> `reply[5] ==` the record's checksum byte
4. `04 83 16 00 00 FF 55 AA` -> leave the bootloader and start the firmware (~180 ms).
5. The servo needs about 2 s to restart; `8A` answers `04 FA ..` until then. Afterwards
   restore the signal source with `AA` if wanted.

### Verified on real hardware (MAX MK2, 2026-11-19)

- Full flash of `Axon_MAX_MK2_Servo_Mode.sfm`: 13 erases + 398 writes, every reply correct
  on the first attempt, about 20 s. Afterwards the parameter block read back byte-identical
  to the block embedded in the image.
- Bootloader reports `V0.3`, ids `08 22`.
- Entering and leaving the bootloader without erasing anything (steps 0, 1, 2, 4) is harmless.
- Not yet flashed on hardware: the CR-mode images.

### Why step 0 matters (the programmer freeze)

With the joystick signal left on during a bootloader session, three things were seen:
`80` sometimes failed (reply status 0), `81` sometimes returned a plain echo, and afterwards
the first `8A` got no reply and the programmer ignored **every** command until its USB was
replugged, even if the servo had been power-cycled with `B0` in between. With the signal
switched off first, none of this happens. The servo itself was never harmed.
The experiments are in `reverse-engineering/scripts/` (`exp1_*.py` reproduces the freeze,
`exp2_*.py` is the working sequence; neither erases anything).
