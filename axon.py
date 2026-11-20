#!/usr/bin/env python3
"""axon - command-line tool for the Axon Servo Programmer MK2 (programs Axon MK2 servos).

Unofficial; not affiliated with Axon Robotics. The USB protocol was worked out
from Axon Software MK2 v1.1.2 and confirmed against a real programmer and a
MAX MK2 servo. See PROTOCOL.md.

    axon                      show adapter, servo and every setting
    axon set left=120 right=120 inversion=on
    axon save my-servo.svp    back up settings to a file
    axon load my-servo.svp    apply settings from a file (--exact = byte-for-byte restore)
    axon default              factory-reset the servo's settings
    axon flash FILE.sfm       load firmware (switch Servo mode <-> CR mode)
    axon pulse 1500           drive the servo from USB (test), 'axon pulse off' to stop
    axon monitor              live voltage / current / pulse readout
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    import hid  # pip install hidapi
except ImportError:  # pragma: no cover
    hid = None

__version__ = "0.2.0"

VID, PID = 0x0473, 0x13AA   # programmer in normal mode
BOOT_VID = 0x0472           # programmer in its own firmware-update mode
RID = 0x04                  # every packet is HID report 4, 64 bytes total

CMD_IDENTIFY = 0x91
CMD_STATUS = 0xAF
CMD_POWER = 0xB0
CMD_DETECT = 0x8A
CMD_READ = 0xCD
CMD_WRITE = 0xCB
CMD_DEFAULT = 0x5A
CMD_SOURCE = 0xAA
CMD_PPM_SET = 0xAB
CMD_PPM_ENABLE = 0xAC
CMD_BOOT_ENTER = 0x80
CMD_BOOT_SEED = 0x81
CMD_BOOT_DATA = 0x82
CMD_BOOT_EXIT = 0x83

BLOCK_LEN = 59   # parameter block the servo exposes
WRITE_LEN = 44   # leading part that is writable (the rest is date + model name)

SOURCES = {0: "none", 1: "usb", 2: "joystick", 3: "ext"}

# AES-128-CBC key the official app uses to unwrap .sfm firmware files (IV = 0).
SFM_KEY = bytes.fromhex("770BACD92801CE8A302DA210CD248D1F")

# The servo's settings are saved here before every write (override with AXON_BACKUP_DIR).
BACKUP_DIR = os.environ.get("AXON_BACKUP_DIR") or os.path.join(os.path.expanduser("~"), "axon-backups")


class AxonError(Exception):
    pass


def hx(data) -> str:
    return " ".join(f"{b:02X}" for b in data)


# --------------------------------------------------------------------------
# USB transport + adapter commands
# --------------------------------------------------------------------------

class Programmer:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.dev = None
        self.product = ""

    # -- plumbing ----------------------------------------------------------

    def open(self) -> "Programmer":
        if hid is None:
            raise AxonError("the 'hidapi' Python package is missing (pip install hidapi)")
        found = hid.enumerate(VID, PID)
        if not found:
            if hid.enumerate(BOOT_VID, PID):
                raise AxonError("the programmer is in its own firmware-update mode; "
                                "unplug it and plug it back in")
            raise AxonError("Axon MK2 programmer not found - is it plugged in over USB?")
        self.dev = hid.device()
        try:
            self.dev.open_path(found[0]["path"])
        except OSError as e:
            raise AxonError(f"could not open the programmer ({e}); is another app using it?")
        self.product = found[0].get("product_string") or ""
        r = self.xfer([CMD_IDENTIFY])
        if r is None or r[5] != 0x22:
            raise AxonError("the device did not identify as an Axon MK2 programmer"
                            + (f" (got {hx(r[:8])})" if r else " (no reply)"))
        return self

    def close(self) -> None:
        if self.dev is not None:
            self.dev.close()
            self.dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def _drain(self) -> None:
        while self.dev.read(64, 1):
            pass

    def xfer(self, payload, *, match=None, timeout=400, tries=3, reply=True):
        """Send one command (payload = bytes after the report id) and return the
        64-byte reply, or None on timeout. `match` is the value expected in
        reply[4]; replies that do not match are skipped, like the official app."""
        pkt = bytes([RID]) + bytes(payload)
        if len(pkt) > 64:
            raise ValueError("packet too long")
        pkt += bytes(64 - len(pkt))
        self._drain()
        if self.verbose:
            print(f"    > {hx(pkt[:28])} ..", file=sys.stderr)
        if self.dev.write(pkt) < 0:
            raise AxonError("USB write failed - was the programmer unplugged?")
        if not reply:
            return None
        for _ in range(tries):
            r = bytes(self.dev.read(64, timeout))
            if not r:
                break
            r += bytes(64 - len(r))
            if self.verbose:
                print(f"    < {hx(r[:28])} ..", file=sys.stderr)
            if match is None or r[4] == match:
                return r
        return None

    # -- adapter -----------------------------------------------------------

    def status(self) -> dict:
        r = self.xfer([CMD_STATUS], match=CMD_STATUS, timeout=200)
        if r is None:
            raise AxonError("the programmer did not answer the status request")
        amps = (r[13] << 8 | r[14]) / 4096 * 3.3 / 0.6
        return {
            "volts": (r[9] << 8 | r[10]) / 4096 * 3.3 * 5.99,
            "amps": 0.0 if amps < 0.08 else min(amps, 5.0),
            "source": r[15],
            "source_name": SOURCES.get(r[15], "joystick" if r[15] in (4, 130) else f"?{r[15]}"),
            "power_on": r[16] == 3,
            "power_state": r[16],
            "pulse_us": r[5] << 8 | r[6],
            "ppm_in": r[19] == 1,
            "ppm_in_period_us": r[20] << 8 | r[21],
            "ppm_in_pulse_us": r[22] << 8 | r[23],
        }

    def power(self, on: bool) -> None:
        self.xfer([CMD_POWER, 0x00, 1 if on else 0])

    def ensure_power(self, force: bool = False) -> dict:
        st = self.status()
        if not st["power_on"]:
            if st["volts"] > 9.1 and not force:
                raise AxonError(f"input voltage is {st['volts']:.1f} V - too high to power the "
                                "servo safely (the official app warns above 9.1 V)")
            self.power(True)
            time.sleep(0.6)
            st = self.status()
        return st

    def set_source(self, source: int) -> None:
        """1 = USB, 2 = joystick, 3 = external receiver."""
        self.xfer([CMD_SOURCE, 0x00, source])

    def ppm_enable(self, pulse=1500, period_us=20000, lo=500, hi=2500, center=1500) -> None:
        def w(v):
            return [(v >> 8) & 0xFF, v & 0xFF]
        self.xfer([CMD_PPM_ENABLE, 0x00] + w(period_us) + w(pulse) + w(hi) + w(lo)
                  + w(center) + w(period_us))

    def ppm_disable(self, period_us=20000, lo=500, hi=2500, center=1500) -> None:
        def w(v):
            return [(v >> 8) & 0xFF, v & 0xFF]
        self.xfer([CMD_PPM_ENABLE, 0x00] + w(0) + w(0) + w(hi) + w(lo) + w(center) + w(period_us))

    def ppm_set(self, pulse: int) -> None:
        self.xfer([CMD_PPM_SET, 0x00, 0x00, 0x00, (pulse >> 8) & 0xFF, pulse & 0xFF])

    # -- servo -------------------------------------------------------------

    def detect(self, tries: int = 1):
        """Return servo identity, or None if no servo answers."""
        for i in range(tries):
            r = self.xfer([CMD_DETECT, 0x00, 0x00, 0x04], match=CMD_DETECT)
            if r is not None and r[1] == 1 and r[7] == 0x22 and r[5] in (0x34, 0x04):
                return {
                    "firmware": f"AISV{r[6]:02X}{r[7]:02X}{r[8]:02X}",
                    "type": r[6],
                    "mode": "cr" if r[6] in (0x41, 0x31) else "servo",
                    "proto": r[5],
                }
            if i + 1 < tries:
                time.sleep(0.2)
        return None

    def require_servo(self) -> dict:
        self.ensure_power()
        servo = self.detect(tries=10)
        if servo is None:
            raise AxonError("no servo detected - check that it is plugged into the programmer "
                            "(signal wire on the correct side)")
        return servo

    def read_block(self) -> bytes:
        for _ in range(3):
            r = self.xfer([CMD_READ, 0x00, 0x00, BLOCK_LEN], match=BLOCK_LEN)
            if r is not None and r[1] == 1:
                return bytes(r[5:5 + BLOCK_LEN])
            time.sleep(0.1)
        raise AxonError("could not read the servo's parameters")

    def write_block(self, block: bytes) -> None:
        """Write the first 44 bytes of `block` to the servo (exactly what the
        official Write button sends: all 59 bytes in the packet, length 44)."""
        if len(block) != BLOCK_LEN:
            raise ValueError("parameter block must be 59 bytes")
        r = self.xfer([CMD_WRITE, 0x00, 0x00, WRITE_LEN] + list(block),
                      match=WRITE_LEN, timeout=1000)
        if r is None or r[1] != 1:
            raise AxonError("the servo did not acknowledge the write"
                            + (f" (got {hx(r[:8])})" if r else " (no reply)"))

    def factory_default(self) -> bool:
        r = self.xfer([CMD_DEFAULT, 0x00, 0x00, 0x01], match=CMD_DEFAULT, timeout=1000)
        return r is not None and r[5] == 0xAA


# --------------------------------------------------------------------------
# Parameter block <-> named settings
# --------------------------------------------------------------------------
#
# 59-byte block (offsets), as laid out by the official app's struct:
#   0 sys-amp   1 damping   2 sensitivity   6 PWM power   7 min-power
#   8 right range   9 left range   10 soft start   12-14 overload levels
#   15-17 overload times (x0.077 s; in CR mode byte 15 is ProPTL x0.1 s)
#   18 signal-mode constant   20 flags   22-23 neutral (int16 LE)
#   26 flags2 (bit0 beep)   32-43 user name ('*' padded)
#   44-46 manufacture day/month/year-2000   47-58 model name ('*' padded)

def _parse_number(text: str, key: str, suffixes: str = "") -> float:
    t = text.strip().lower()
    for s in suffixes:
        if t.endswith(s):
            t = t[: -len(s)].strip()
    try:
        return float(t)
    except ValueError:
        raise AxonError(f"{key}: '{text}' is not a number")


def _parse_bool(text: str, key: str) -> bool:
    t = text.strip().lower()
    if t in ("on", "1", "true", "yes", "y"):
        return True
    if t in ("off", "0", "false", "no", "n"):
        return False
    raise AxonError(f"{key}: use on or off (got '{text}')")


class Setting:
    key = ""
    label = ""
    hint = ""
    advanced = False

    def read(self, b) -> str:
        raise NotImplementedError

    def write(self, b: bytearray, text: str) -> None:
        raise NotImplementedError

    def copy(self, src, dst: bytearray) -> None:
        """Copy this setting's raw bits from one block to another (lossless)."""
        raise NotImplementedError


def _copy_bits(src, dst, off, mask=0xFF):
    dst[off] = (dst[off] & ~mask & 0xFF) | (src[off] & mask)


class IntSetting(Setting):
    def __init__(self, key, label, off, lo, hi, *, int16=False, advanced=False, note=""):
        self.key, self.label, self.off, self.lo, self.hi = key, label, off, lo, hi
        self.int16, self.advanced = int16, advanced
        self.hint = f"{lo}..{hi}" + (f"  {note}" if note else "")

    def read(self, b) -> str:
        if self.int16:
            return str(int.from_bytes(b[self.off:self.off + 2], "little", signed=True))
        return str(b[self.off])

    def write(self, b, text):
        v = _parse_number(text, self.key)
        if v != int(v) or not self.lo <= v <= self.hi:
            raise AxonError(f"{self.key}: must be a whole number {self.lo}..{self.hi}")
        if self.int16:
            b[self.off:self.off + 2] = int(v).to_bytes(2, "little", signed=True)
        else:
            b[self.off] = int(v)

    def copy(self, src, dst):
        for i in range(2 if self.int16 else 1):
            dst[self.off + i] = src[self.off + i]


class PercentSetting(Setting):
    """Stored as 0..255 = 0..100 %."""

    def __init__(self, key, label, off, lo, hi, *, raw_min=0):
        self.key, self.label, self.off, self.lo, self.hi, self.raw_min = key, label, off, lo, hi, raw_min
        self.hint = f"{lo}..{hi} %"

    def read(self, b) -> str:
        return f"{b[self.off] * 100 / 255:.1f}%"

    def write(self, b, text):
        v = _parse_number(text, self.key, "%")
        if not self.lo <= v <= self.hi:
            raise AxonError(f"{self.key}: must be {self.lo}..{self.hi} (percent)")
        b[self.off] = max(self.raw_min, min(255, int(0.01 + v * 255 / 100)))

    def copy(self, src, dst):
        dst[self.off] = src[self.off]


class SecondsSetting(Setting):
    def __init__(self, key, label, off, scale, lo, hi, *, rounded=False):
        self.key, self.label, self.off, self.scale = key, label, off, scale
        self.lo, self.hi, self.rounded = lo, hi, rounded
        self.hint = f"{lo}..{hi} s"

    def read(self, b) -> str:
        return f"{b[self.off] * self.scale:.1f}s"

    def write(self, b, text):
        v = _parse_number(text, self.key, "s")
        if not self.lo <= v <= self.hi:
            raise AxonError(f"{self.key}: must be {self.lo}..{self.hi} (seconds)")
        raw = round(v / self.scale) if self.rounded else int(0.01 + v / self.scale)
        b[self.off] = max(0, min(255, raw))

    def copy(self, src, dst):
        dst[self.off] = src[self.off]


class BitSetting(Setting):
    def __init__(self, key, label, off, mask):
        self.key, self.label, self.off, self.mask = key, label, off, mask
        self.hint = "on | off"

    def read(self, b) -> str:
        return "on" if b[self.off] & self.mask else "off"

    def write(self, b, text):
        if _parse_bool(text, self.key):
            b[self.off] |= self.mask
        else:
            b[self.off] &= ~self.mask & 0xFF

    def copy(self, src, dst):
        _copy_bits(src, dst, self.off, self.mask)


class SensitivitySetting(Setting):
    key, label = "sensitivity", "Sensitivity"
    LEVELS = [("ultra-high", 25), ("high", 50), ("medium", 100), ("low", 150)]
    hint = " | ".join(n for n, _ in LEVELS)

    def read(self, b) -> str:
        for name, top in self.LEVELS[:3]:
            if b[2] <= top:
                return name
        return "low"

    def write(self, b, text):
        t = text.strip().lower().replace("_", "-").replace(" ", "-")
        t = {"ultra": "ultra-high", "ultrahigh": "ultra-high", "mid": "medium"}.get(t, t)
        for name, raw in self.LEVELS:
            if t == name:
                b[2] = raw
                return
        raise AxonError(f"sensitivity: choose one of {self.hint}")

    def copy(self, src, dst):
        dst[2] = src[2]


class SoftStartSetting(Setting):
    key, label, hint = "soft-start", "Soft Start", "1..11  (level)"

    def read(self, b) -> str:
        return str(b[10]) if b[10] <= 10 else "11"

    def write(self, b, text):
        v = _parse_number(text, self.key)
        if v != int(v) or not 1 <= v <= 11:
            raise AxonError("soft-start: must be a level 1..11")
        b[10] = 0xFF if v == 11 else int(v)

    def copy(self, src, dst):
        dst[10] = src[10]


class LosePpmSetting(Setting):
    key, label = "lose-ppm", "Lose PPM Protection"
    hint = "release | keep | neutral"

    def read(self, b) -> str:
        if b[20] & 0x40:
            return "neutral" if b[20] & 0x08 else "keep"
        return "release"

    def write(self, b, text):
        t = text.strip().lower()
        if t == "release":
            b[20] &= 0xB7
        elif t in ("keep", "keep-position", "hold"):
            b[20] = (b[20] & 0xF7) | 0x40
        elif t in ("neutral", "go-neutral", "center"):
            b[20] |= 0x48
        else:
            raise AxonError(f"lose-ppm: choose one of {self.hint}")

    def copy(self, src, dst):
        _copy_bits(src, dst, 20, 0x48)


class SignalSetting(Setting):
    key, label = "signal", "Signal mode"
    hint = "normal | sanwa-sr | futaba-sr | futaba-ur"

    def read(self, b) -> str:
        if b[20] & 0x10:
            return "futaba-sr"
        if b[20] & 0x80:
            return {220: "sanwa-sr", 143: "futaba-ur"}.get(b[18], f"special-0x{b[18]:02X}")
        return "normal"

    def write(self, b, text):
        t = text.strip().lower().replace("_", "-").replace(" ", "-")
        if t == "normal":
            b[20] &= 0x6F
            b[18] = 220   # factory value in every firmware image
        elif t == "futaba-sr":
            b[20] = (b[20] | 0x10) & 0x7F
        elif t in ("sanwa-sr", "sanwa"):
            b[20] = (b[20] | 0x80) & 0xEF
            b[18] = 220
        elif t == "futaba-ur":
            b[20] = (b[20] | 0x80) & 0xEF
            b[18] = 143
        else:
            raise AxonError(f"signal: choose one of {self.hint}")

    def copy(self, src, dst):
        _copy_bits(src, dst, 20, 0x90)
        if src[20] & 0x80:
            dst[18] = src[18]


class NameSetting(Setting):
    key, label, hint = "name", "User name", "up to 12 letters/digits"

    def read(self, b) -> str:
        return bytes(b[32:44]).decode("ascii", "replace").rstrip("*")

    def write(self, b, text):
        try:
            raw = text.encode("ascii")
        except UnicodeEncodeError:
            raise AxonError("name: plain ASCII only")
        if len(raw) > 12 or any(c < 0x20 or c > 0x7E for c in raw):
            raise AxonError("name: at most 12 printable characters")
        b[32:44] = raw + b"*" * (12 - len(raw))

    def copy(self, src, dst):
        dst[32:44] = src[32:44]


SERVO_SETTINGS = [
    IntSetting("left", "L range", 9, 10, 255, note="(factory 250)"),
    IntSetting("right", "R range", 8, 10, 255, note="(factory 250)"),
    IntSetting("neutral", "Neutral", 22, -25, 25, int16=True),
    IntSetting("damping", "Damping Factor", 1, 1, 255),
    PercentSetting("power", "PWM Power", 6, 10, 100, raw_min=25),
    SensitivitySetting(),
    BitSetting("inversion", "Inversion", 20, 0x01),
    SoftStartSetting(),
    LosePpmSetting(),
    PercentSetting("ol1-level", "Overload L1 power", 12, 10, 100),
    SecondsSetting("ol1-time", "Overload L1 after", 15, 0.077, 0, 10.5),
    PercentSetting("ol2-level", "Overload L2 power", 13, 10, 100),
    SecondsSetting("ol2-time", "Overload L2 after", 16, 0.077, 0, 10.5),
    PercentSetting("ol3-level", "Overload L3 power", 14, 10, 100),
    SecondsSetting("ol3-time", "Overload L3 after", 17, 0.077, 0, 10.5),
    SignalSetting(),
    BitSetting("beep", "Beep", 26, 0x01),
    NameSetting(),
    IntSetting("min-power", "MinPower", 7, 1, 255, advanced=True),
    IntSetting("sys-amp", "SysAmp", 0, 6, 255, advanced=True),
]

# Continuous-rotation firmware: the official app only exposes these four.
CR_SETTINGS = [
    PercentSetting("power", "PWM Power", 6, 10, 100, raw_min=25),
    BitSetting("inversion", "Inversion", 20, 0x01),
    SecondsSetting("proptl", "ProPTL", 15, 0.1, 0.1, 25.0, rounded=True),
    BitSetting("beep", "Beep", 26, 0x01),
]


def settings_for(mode: str):
    return CR_SETTINGS if mode == "cr" else SERVO_SETTINGS


def model_name(block) -> str:
    return bytes(block[47:59]).decode("ascii", "replace").rstrip("*")


def made_date(block) -> str:
    return f"{block[46] + 2000:04d}-{block[45]:02d}-{block[44]:02d}"


def decode(block, mode: str) -> dict:
    return {s.key: s.read(block) for s in settings_for(mode)}


def apply_changes(block: bytes, mode: str, changes: dict, allow_advanced: bool) -> bytearray:
    table = {s.key: s for s in settings_for(mode)}
    new = bytearray(block)
    for key, value in changes.items():
        k = key.strip().lower().replace("_", "-")
        if k not in table:
            where = "CR-mode" if mode == "cr" else "servo-mode"
            raise AxonError(f"unknown {where} setting '{key}' - valid: {', '.join(table)}")
        if table[k].advanced and not allow_advanced:
            raise AxonError(f"'{k}' is a hidden factory tuning value; add --advanced if you "
                            "really want to change it")
        table[k].write(new, value)
    return new


# --------------------------------------------------------------------------
# .svp settings files (same format the official app saves)
# --------------------------------------------------------------------------

def svp_bytes(block: bytes) -> bytes:
    out = bytearray(95)
    out[:BLOCK_LEN] = block
    out[93], out[94] = 0x56, 0x34
    return bytes(out)


def svp_load(path: str) -> bytes:
    with open(path, "rb") as f:
        data = f.read()
    if len(data) != 95 or data[93] != 0x56:
        raise AxonError(f"{path} is not an Axon MK2 .svp settings file")
    if data[94] < 0x34:
        raise AxonError(f"{path} is from an older software version and cannot be used")
    return data[:BLOCK_LEN]


def backup(block: bytes, tag: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"{model_name(block) or 'servo'}-{time.strftime('%Y%m%d-%H%M%S')}-{tag}.svp"
    path = os.path.join(BACKUP_DIR, name)
    with open(path, "wb") as f:
        f.write(svp_bytes(block))
    return path


# --------------------------------------------------------------------------
# Firmware (.sfm) files: AES-128-CBC wrapped text of '$' erase + Intel HEX lines
# --------------------------------------------------------------------------

def _gmul(a: int, b: int) -> int:
    p = 0
    while b:
        if b & 1:
            p ^= a
        a = ((a << 1) ^ 0x11B) if a & 0x80 else a << 1
        b >>= 1
    return p


def _build_sbox():
    sbox = [0] * 256
    for x in range(256):
        inv = 0 if x == 0 else next(y for y in range(1, 256) if _gmul(x, y) == 1)
        s = inv
        for shift in (1, 2, 3, 4):
            s ^= ((inv << shift) | (inv >> (8 - shift))) & 0xFF
        sbox[x] = s ^ 0x63
    inv_sbox = [0] * 256
    for i, v in enumerate(sbox):
        inv_sbox[v] = i
    return sbox, inv_sbox


def aes128_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if len(key) != 16 or len(iv) != 16 or len(data) % 16:
        raise ValueError("bad AES input sizes")
    sbox, inv_sbox = _build_sbox()
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(words[i - 1])
        if i % 4 == 0:
            t = [sbox[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _gmul(rcon, 2)
        words.append([words[i - 4][j] ^ t[j] for j in range(4)])
    rk = [sum(words[4 * r:4 * r + 4], []) for r in range(11)]
    m9, m11, m13, m14 = ([_gmul(x, k) for x in range(256)] for k in (9, 11, 13, 14))
    unshift = [(r + 4 * ((c - r) % 4)) for c in range(4) for r in range(4)]

    out = bytearray()
    prev = iv
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        s = [blk[i] ^ rk[10][i] for i in range(16)]
        for rnd in range(9, -1, -1):
            s = [inv_sbox[s[unshift[i]]] ^ rk[rnd][i] for i in range(16)]
            if rnd:
                t = []
                for c in range(0, 16, 4):
                    a0, a1, a2, a3 = s[c:c + 4]
                    t += [m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3],
                          m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3],
                          m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3],
                          m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3]]
                s = t
        out += bytes(s[i] ^ prev[i] for i in range(16))
        prev = blk
    return bytes(out)


class Firmware:
    def __init__(self, path: str):
        with open(path, "rb") as f:
            raw = f.read()
        if len(raw) > 65536 or len(raw) <= 32 or (len(raw) - 16) % 16:
            raise AxonError(f"{path} does not look like a servo firmware (.sfm) file")
        text = aes128_cbc_decrypt(SFM_KEY, bytes(16), raw[16:]).replace(b"\x00", b"")
        try:
            lines = [ln.strip() for ln in text.decode("ascii").splitlines() if ln.strip()]
        except UnicodeDecodeError:
            raise AxonError(f"{path} did not decrypt to a valid firmware image")
        if not lines or not lines[0].startswith("@") or len(lines[0]) < 5:
            raise AxonError(f"{path} did not decrypt to a valid firmware image")
        head = lines[0]
        self.path = path
        self.id1, self.id2 = int(head[1:3], 16), int(head[3:5], 16)
        self.model = head[5:].replace(" ", "")
        self.erases = []    # (b1, b2)
        self.records = []   # raw Intel HEX record bytes, data records only
        self.steps = []     # ("erase", (b1, b2)) / ("write", record) in file order
        mem = {}
        for ln in lines[1:]:
            if ln.startswith("$"):
                e = (int(ln[1:3], 16), int(ln[3:5], 16))
                self.erases.append(e)
                self.steps.append(("erase", e))
            elif ln.startswith(":"):
                rec = bytes.fromhex(ln[1:])
                if len(rec) != rec[0] + 5 or sum(rec) & 0xFF:
                    raise AxonError(f"{path}: corrupt hex record '{ln}'")
                if rec[3] == 0x00:
                    if len(rec) > 21:
                        raise AxonError(f"{path}: hex record too long for the bootloader")
                    self.records.append(rec)
                    self.steps.append(("write", rec))
                    addr = rec[1] << 8 | rec[2]
                    for i in range(rec[0]):
                        mem[addr + i] = rec[4 + i]
            else:
                raise AxonError(f"{path}: unexpected line '{ln[:20]}'")
        if not self.records:
            raise AxonError(f"{path}: no firmware data found")
        self.mem = mem
        tag = bytes(mem.get(a, 0x20) for a in range(0x1AF0, 0x1AFF))
        self.build = tag.decode("ascii", "replace").strip() if tag.isascii() else ""
        self.defaults = bytes(mem.get(0x1C01 + i, 0xFF) for i in range(BLOCK_LEN))

    def summary(self) -> str:
        return (f"model {self.model}, build '{self.build}', {len(self.mem)} bytes, "
                f"{len(self.erases)} page erases, {len(self.records)} records")


def flash(prog: Programmer, fw: Firmware, *, expect_model, progress=None) -> str:
    """Run the bootloader conversation. Returns the bootloader version string.
    `expect_model` None skips the model-name check (recovery)."""
    if expect_model is not None and fw.model != expect_model:
        raise AxonError(f"this firmware is for '{fw.model}' but the servo is '{expect_model}'")

    # The programmer must not be driving a servo signal (joystick, USB or
    # receiver) during a bootloader session - the official app switches it off
    # first. Left on, bootloader replies get corrupted and the programmer
    # freezes on the next detect until it is replugged. No status/detect
    # requests may be sent between "enter" and "exit" either.
    if prog.status()["source"] != 0:
        prog.ppm_disable()
        time.sleep(0.3)
        if prog.status()["source"] != 0:
            raise AxonError("could not switch the programmer's signal output off - not flashing")

    def boot_exit():
        prog.xfer([CMD_BOOT_EXIT, 22, 0x00, 0x00, 0xFF, 0x55, 0xAA], timeout=3000)

    r = prog.xfer([CMD_BOOT_ENTER, 0x04, 0x01, 0x02, 0x03, 0x04], timeout=3000)
    if r is None or r[1] != 1 or r[5] != 0x56:
        boot_exit()
        raise AxonError("the servo's bootloader did not answer"
                        + (f" (got {hx(r[:12])})" if r else ""))
    boot_version = bytes(r[5:9]).decode("ascii", "replace")
    if (r[9], r[10]) != (fw.id1, fw.id2):
        boot_exit()
        raise AxonError(f"firmware is for bootloader id {fw.id1:02X}{fw.id2:02X} but the servo "
                        f"reports {r[9]:02X}{r[10]:02X} - wrong file for this servo")

    rnd = os.urandom(22)
    r = prog.xfer([CMD_BOOT_SEED, 22] + list(rnd), timeout=3000)
    if r is None or r[1] != 1 or bytes(r[3:25]) == rnd:
        # an echo of our own bytes means the bootloader itself never answered
        boot_exit()
        raise AxonError("the bootloader did not complete the key exchange (nothing was erased)")
    seed = bytes(rnd[i] ^ r[i + 5] for i in range(22))

    def send(body: bytes, want: int, what: str):
        # body = bytes for packet positions 3.. ; positions 3..24 are XOR-masked
        pkt = bytearray([CMD_BOOT_DATA, 22]) + bytearray(body)
        pkt += os.urandom(63 - len(pkt))
        for i in range(22):
            pkt[2 + i] ^= seed[i]
        last = None
        for _attempt in range(4):
            last = prog.xfer(bytes(pkt), timeout=1500)
            if last is not None and last[5] == want:
                return
            time.sleep(0.05)
        raise AxonError(f"{what} failed (servo answered "
                        f"{hx(last[:8]) if last else 'nothing'}). The servo is still in its "
                        "bootloader: leave everything plugged in and run the flash again with "
                        "--recover")

    total = len(fw.steps)
    for n, (kind, item) in enumerate(fw.steps, 1):
        if kind == "erase":
            send(bytes([0x0A, item[0], item[1]]), 0x55, f"erasing page {item[0]:02X}{item[1]:02X}")
        else:
            send(bytes([0x3A]) + item, item[-1],
                 f"writing address {item[1]:02X}{item[2]:02X}")
        if progress:
            progress(n, total)
    boot_exit()
    return boot_version


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise AxonError("needs confirmation - rerun with --yes")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def print_adapter(prog: Programmer, st: dict) -> None:
    print(f"Adapter   Axon Programmer MK2 ({prog.product})   {st['volts']:.2f} V   "
          f"{st['amps']:.2f} A   servo power {'on' if st['power_on'] else 'off'}   "
          f"signal source: {st['source_name']} ({st['pulse_us']} us)")


def print_servo(servo: dict, block: bytes) -> None:
    mode = "CR (continuous rotation)" if servo["mode"] == "cr" else "Servo (positional)"
    print(f"Servo     {model_name(block)}   firmware {servo['firmware']}   mode: {mode}   "
          f"made {made_date(block)}")


def print_settings(block: bytes, mode: str, show_advanced: bool, old: bytes = None) -> None:
    print()
    print(f"  {'setting':<12} {'value':<14} {'':<22} allowed")
    for s in settings_for(mode):
        if s.advanced and not show_advanced:
            continue
        val = s.read(block)
        mark = ""
        if old is not None and s.read(old) != val:
            mark = f"(was {s.read(old)})"
        print(f"  {s.key:<12} {val:<14} {mark:<22} {s.hint}{'  [advanced]' if s.advanced else ''}")


def cmd_info(args) -> int:
    with Programmer(args.verbose) as prog:
        st = prog.ensure_power()
        servo = prog.detect(tries=10)
        block = prog.read_block() if servo else None
        if args.json:
            out = {"adapter": {k: st[k] for k in ("volts", "amps", "power_on", "source_name", "pulse_us")}}
            if servo:
                out["servo"] = {"model": model_name(block), "firmware": servo["firmware"],
                                "mode": servo["mode"], "made": made_date(block)}
                out["settings"] = decode(block, servo["mode"])
                out["raw"] = block.hex()
            print(json.dumps(out, indent=2))
            return 0
        print_adapter(prog, st)
        if not servo:
            print("Servo     none detected - plug a servo into the programmer")
            return 1
        print_servo(servo, block)
        print_settings(block, servo["mode"], args.advanced)
        if args.advanced:
            print(f"\n  raw block: {hx(block)}")
        print("\nChange with:  axon set <setting>=<value> ...")
    return 0


def write_and_verify(prog: Programmer, old: bytes, new: bytes, mode: str, advanced: bool) -> int:
    path = backup(old, "before")
    prog.write_block(bytes(new))
    time.sleep(0.15)
    back = prog.read_block()
    ok = back[:WRITE_LEN] == bytes(new[:WRITE_LEN])
    print_settings(back, mode, advanced, old=old)
    print()
    if ok:
        print("Written and verified by reading back from the servo.")
    else:
        bad = [i for i in range(WRITE_LEN) if back[i] != new[i]]
        print(f"WARNING: the servo did not keep every value (differing bytes at {bad}).")
    print(f"Previous settings saved to {path}")
    return 0 if ok else 2


def cmd_set(args) -> int:
    changes = {}
    for item in args.assignments:
        if "=" not in item:
            raise AxonError(f"'{item}' should look like setting=value")
        k, v = item.split("=", 1)
        changes[k] = v
    with Programmer(args.verbose) as prog:
        servo = prog.require_servo()
        old = prog.read_block()
        new = apply_changes(old, servo["mode"], changes, args.advanced)
        if bytes(new[:WRITE_LEN]) == old[:WRITE_LEN]:
            print("Nothing to change - the servo already has those values.")
            return 0
        if args.dry_run:
            print_settings(bytes(new), servo["mode"], args.advanced, old=old)
            print("\n(dry run - nothing written)")
            return 0
        return write_and_verify(prog, old, new, servo["mode"], args.advanced)


def cmd_save(args) -> int:
    with Programmer(args.verbose) as prog:
        prog.require_servo()
        block = prog.read_block()
    with open(args.file, "wb") as f:
        f.write(svp_bytes(block))
    print(f"Saved {model_name(block)} settings to {args.file}")
    return 0


def cmd_load(args) -> int:
    src = svp_load(args.file)
    with Programmer(args.verbose) as prog:
        servo = prog.require_servo()
        old = prog.read_block()
        if model_name(src) and model_name(src) != model_name(old) and not args.force:
            raise AxonError(f"{args.file} was saved from a '{model_name(src)}' but this servo is "
                            f"a '{model_name(old)}' (use --force to apply anyway)")
        new = bytearray(old)
        if args.exact:
            # Byte-for-byte restore of the writable region (same model only).
            if model_name(src) != model_name(old):
                raise AxonError("--exact only works with a file saved from the same servo model")
            new[:WRITE_LEN] = src[:WRITE_LEN]
        else:
            # Copy only the named settings, never raw calibration bytes.
            for s in settings_for(servo["mode"]):
                if not s.advanced:
                    s.copy(src, new)
        if bytes(new[:WRITE_LEN]) == old[:WRITE_LEN]:
            print("The servo already matches that file.")
            return 0
        print_settings(bytes(new), servo["mode"], args.exact, old=old)
        if not confirm("\nWrite these settings to the servo?", args.yes):
            print("Cancelled.")
            return 1
        return write_and_verify(prog, old, new, servo["mode"], args.exact)


def cmd_default(args) -> int:
    with Programmer(args.verbose) as prog:
        servo = prog.require_servo()
        old = prog.read_block()
        if not confirm(f"Reset {model_name(old)} to factory default settings?", args.yes):
            print("Cancelled.")
            return 1
        path = backup(old, "before-default")
        if not prog.factory_default():
            raise AxonError("the servo refused the factory-default command")
        time.sleep(0.3)
        new = prog.read_block()
        print_settings(new, servo["mode"], False, old=old)
        print(f"\nFactory defaults restored. Previous settings saved to {path}")
    return 0


def cmd_flash(args) -> int:
    fw = Firmware(args.file)
    print(f"Firmware  {os.path.basename(args.file)}: {fw.summary()}")
    if args.dry_run:
        print(f"          default settings block in this image: {hx(fw.defaults[:WRITE_LEN])}")
        print("(dry run - nothing sent to the servo)")
        return 0
    with Programmer(args.verbose) as prog:
        st = prog.status()
        orig_source = st["source"]
        if not st["power_on"]:
            prog.ensure_power()
            time.sleep(3.0)   # let the servo finish starting up before the bootloader request
        old = None
        if args.recover:
            expect = None
            print("Recovery mode: skipping servo detection and model check.")
        else:
            servo = prog.require_servo()
            old = prog.read_block()
            expect = model_name(old)
            print_servo(servo, old)
        print("\nFlashing replaces the servo's firmware and resets ALL its settings to that "
              "firmware's defaults.\nUntil it finishes (about 30 s): do not unplug anything and do "
              "not touch the programmer's joystick or buttons.")
        if not confirm(f"Flash {fw.model} firmware '{fw.build}' now?", args.yes):
            print("Cancelled.")
            return 1
        if old is not None:
            print(f"Current settings saved to {backup(old, 'before-flash')}")

        def progress(n, total):
            if n == total or n % 8 == 0:
                print(f"\r  {n * 100 // total:3d}%  ({n}/{total})", end="", flush=True)

        boot = flash(prog, fw, expect_model=expect, progress=progress)
        print(f"\nFlash complete (bootloader {boot}). Restarting servo...")
        time.sleep(0.8)
        servo = prog.detect(tries=40)
        if orig_source in (2, 3):
            prog.set_source(orig_source)   # hand the signal back to the joystick / receiver
        if not servo:
            print("The servo has not re-appeared yet. Unplug it from the programmer, plug it "
                  "back in, and run 'axon'.")
            return 2
        block = prog.read_block()
        print_servo(servo, block)
        print_settings(block, servo["mode"], False)
    return 0


def cmd_pulse(args) -> int:
    with Programmer(args.verbose) as prog:
        st = prog.ensure_power()
        what = args.value.lower()
        if what in ("off", "stop"):
            prog.ppm_disable()
            print("USB pulse output off.")
        elif what == "joystick":
            prog.set_source(2)
            print("Signal source set to the programmer's joystick.")
        else:
            us = _parse_number(what, "pulse", ["us"])
            if us != int(us) or not 500 <= us <= 2500:
                raise AxonError("pulse: give a pulse width 500..2500 (microseconds), 'off' or 'joystick'")
            us = int(us)
            if st["source"] != 1:
                prog.ppm_enable(pulse=us, period_us=args.period_ms * 1000)
                time.sleep(0.1)
            prog.ppm_set(us)
            print(f"Driving the servo from USB at {us} us. 'axon pulse off' stops, "
                  "'axon pulse joystick' hands control back to the joystick.")
        time.sleep(0.15)
        st = prog.status()
        print(f"source: {st['source_name']}   pulse: {st['pulse_us']} us   {st['amps']:.2f} A")
    return 0


def cmd_monitor(args) -> int:
    with Programmer(args.verbose) as prog:
        print("Live adapter readout - Ctrl-C to stop")
        try:
            while True:
                st = prog.status()
                extra = (f"   PPM in: {st['ppm_in_pulse_us']} us" if st["ppm_in"] else "")
                print(f"\r{st['volts']:5.2f} V  {st['amps']:4.2f} A  {st['volts'] * st['amps']:5.1f} W   "
                      f"source {st['source_name']:<8} pulse {st['pulse_us']:4d} us{extra}   ",
                      end="", flush=True)
                time.sleep(0.15)
        except KeyboardInterrupt:
            print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="axon", description="Program Axon MK2 servos through the Axon Servo Programmer MK2.")
    p.add_argument("-v", "--verbose", action="store_true", help="show raw USB packets")
    p.add_argument("--version", action="version", version=f"axon {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("info", help="show adapter, servo and settings (default)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--advanced", action="store_true", help="also show hidden factory values")
    s.set_defaults(fn=cmd_info)

    s = sub.add_parser("set", help="change settings, e.g. axon set left=120 inversion=on")
    s.add_argument("assignments", nargs="+", metavar="setting=value")
    s.add_argument("--advanced", action="store_true", help="allow hidden factory values")
    s.add_argument("--dry-run", action="store_true", help="show the result without writing")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("save", help="save the servo's settings to a .svp file")
    s.add_argument("file")
    s.set_defaults(fn=cmd_save)

    s = sub.add_parser("load", help="apply settings from a .svp file")
    s.add_argument("file")
    s.add_argument("--force", action="store_true", help="apply even if the model differs")
    s.add_argument("--exact", action="store_true",
                   help="byte-for-byte restore of a backup from the same model")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_load)

    s = sub.add_parser("default", help="reset the servo's settings to factory defaults")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_default)

    s = sub.add_parser("flash", help="load a .sfm firmware (Servo mode <-> CR mode)")
    s.add_argument("file")
    s.add_argument("--dry-run", action="store_true", help="only decode and describe the file")
    s.add_argument("--recover", action="store_true",
                   help="skip servo detection (use after an interrupted flash)")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_flash)

    s = sub.add_parser("pulse", help="drive the servo from USB: a width in us, 'off' or 'joystick'")
    s.add_argument("value")
    s.add_argument("--period-ms", type=int, default=20, choices=range(3, 26), metavar="3..25",
                   help="refresh period (default 20 ms = 50 Hz)")
    s.set_defaults(fn=cmd_pulse)

    s = sub.add_parser("monitor", help="live voltage / current / pulse readout")
    s.set_defaults(fn=cmd_monitor)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = ("info", "set", "save", "load", "default", "flash", "pulse", "monitor")
    if not any(a in commands or a in ("-h", "--help", "--version") for a in argv):
        front = [a for a in argv if a in ("-v", "--verbose")]
        argv = front + ["info"] + [a for a in argv if a not in front]
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except AxonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
