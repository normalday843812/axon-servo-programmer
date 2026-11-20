"""E2 (non-destructive): same handshake as before, but first switch the programmer's
signal output off (what the official app does), and send no status polls inside the
bootloader session. Question: does detect work afterwards without freezing?"""
import os, sys, time
from bootlab import axon, raw, alive, log, header

header("E2: AC(off) -> 80 -> 81 -> 83 -> 8A")
with axon.Programmer() as p:
    p.require_servo()
    before = p.read_block()
    st = p.status()
    log("baseline ok; source", st["source_name"], "power", st["power_on"])
    # signal output off, exactly like the official app before an update
    raw(p, [0xAC, 0, 0, 0, 0, 0, 0x09, 0xC4, 0x01, 0xF4, 0x05, 0xDC, 0x4E, 0x20], label="signal off")
    time.sleep(0.3)
    st = p.status(); log("source now:", st["source_name"])
    r = raw(p, [0x80, 4, 1, 2, 3, 4], timeout=3000, label="boot enter")
    entered = bool(r) and r[1] == 1 and r[5] == 0x56
    log("entered bootloader:", entered, "version", bytes(r[5:9]) if entered else None)
    if entered:
        rnd = os.urandom(22)
        r = raw(p, [0x81, 22] + list(rnd), timeout=3000, label="boot seed", show=28)
        if r:
            log("seed reply is just an echo of my bytes:", r[3:25] == rnd, "| key bytes:", axon.hx(r[5:27]))
    raw(p, [0x83, 22, 0, 0, 0xFF, 0x55, 0xAA], timeout=3000, label="boot exit")
    time.sleep(0.6)
    if not alive(p, "status(after)"): log("FROZEN after exit, before any detect"); sys.exit(2)
    ok = False
    for i in range(8):
        r = raw(p, [0x8A, 0, 0, 4], timeout=1500, label=f"detect #{i+1}")
        if r is None:
            log("detect: NO REPLY. programmer alive:", alive(p, "status?")); sys.exit(2)
        if r[1] == 1:
            ok = True; break
        time.sleep(0.4)
    if ok:
        after = p.read_block()
        log("RESULT: detect works after the session, no freeze; block unchanged:", after == before)
    else:
        log("RESULT: programmer alive, servo not answering yet")
    raw(p, [0xAA, 0, 2], label="joystick back")
    time.sleep(0.2)
    log("final source:", p.status()["source_name"])
