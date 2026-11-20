"""Shared helpers for bootloader experiments: raw packet exchange with timestamps,
logged to stdout and appended to boot-experiments.log next to this file."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))   # repo root
import axon

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boot-experiments.log")
_t0 = time.time()
_fh = open(LOG, "a")

def log(*a):
    line = f"[{time.time() - _t0:7.2f}] " + " ".join(str(x) for x in a)
    print(line, flush=True)
    _fh.write(line + "\n"); _fh.flush()

def header(title):
    _fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {title} =====\n"); _fh.flush()
    print(f"===== {title} =====", flush=True)

def raw(p, payload, timeout=600, label="", show=24):
    """Send one packet, return the reply bytes or None. Never retries."""
    pkt = bytes([4]) + bytes(payload); pkt += bytes(64 - len(pkt))
    while p.dev.read(64, 1):
        pass
    t = time.time()
    p.dev.write(pkt)
    r = bytes(p.dev.read(64, timeout))
    dt = time.time() - t
    log(f"{label:16s} > {axon.hx(pkt[:10])} | {dt*1000:5.0f} ms | < {axon.hx(r[:show]) if r else 'NO REPLY'}")
    return r or None

def alive(p, label="status"):
    r = raw(p, [0xAF], timeout=400, label=label, show=20)
    return r is not None and r[4] == 0xAF
