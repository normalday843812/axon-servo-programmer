"""E1 (non-destructive): enter bootloader, key exchange, exit, then power-cycle the
servo with B0 BEFORE the first detect. Question: does detect still freeze the programmer?"""
import os, sys, time
from bootlab import axon, raw, alive, log, header

header("E1: 80 -> 81 -> 83 -> B0 off/on -> 8A")
with axon.Programmer() as p:
    p.require_servo()
    before = p.read_block()
    log("baseline block read ok; model", axon.model_name(before))
    r = raw(p, [0x80, 4, 1, 2, 3, 4], timeout=3000, label="boot enter")
    entered = bool(r) and r[1] == 1 and r[5] == 0x56
    log("entered bootloader:", entered, "version", bytes(r[5:9]) if entered else None)
    if not alive(p, "status(boot)"): log("FROZEN right after 80"); sys.exit(2)
    if entered:
        raw(p, [0x81, 22] + list(os.urandom(22)), timeout=3000, label="boot seed", show=28)
        raw(p, [0x83, 22, 0, 0, 0xFF, 0x55, 0xAA], timeout=3000, label="boot exit")
    for i in range(3):
        time.sleep(0.3)
        if not alive(p, "status(after)"): log("FROZEN after exit, before any detect"); sys.exit(2)
    raw(p, [0xB0, 0, 0], label="servo power off"); time.sleep(2.0)
    if not alive(p): log("FROZEN after power off"); sys.exit(2)
    raw(p, [0xB0, 0, 1], label="servo power on"); time.sleep(2.5)
    if not alive(p): log("FROZEN after power on"); sys.exit(2)
    r = raw(p, [0x8A, 0, 0, 4], timeout=1500, label="detect")
    if r is None:
        log("detect: NO REPLY. programmer alive:", alive(p, "status?"))
        sys.exit(2)
    log("detect replied; servo present:", r[1] == 1)
    if r[1] != 1:
        for i in range(5):
            time.sleep(0.5)
            r = raw(p, [0x8A, 0, 0, 4], timeout=1500, label=f"detect retry {i+1}")
            if r is None: log("NO REPLY on retry; alive:", alive(p, "status?")); sys.exit(2)
            if r[1] == 1: break
    if r[1] == 1:
        after = p.read_block()
        log("RESULT: detect works after servo power-cycle; block unchanged:", after == before)
    else:
        log("RESULT: programmer alive but servo not answering")
