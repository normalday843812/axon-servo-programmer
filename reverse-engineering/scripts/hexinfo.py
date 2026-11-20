import sys
def load(fn):
    mem = {}
    recs = []
    for line in open(fn, 'rb').read().replace(b'\x00', b'').decode('ascii', 'replace').splitlines():
        line = line.strip()
        if not line.startswith(':'):
            if line: recs.append(line)
            continue
        b = bytes.fromhex(line[1:])
        n, addr, typ = b[0], (b[1] << 8) | b[2], b[3]
        assert (sum(b) & 0xFF) == 0, line
        if typ == 0:
            for i in range(n):
                mem[addr + i] = b[4 + i]
        else:
            recs.append(f"type{typ:02X}:{line}")
    return mem, recs
for fn in sys.argv[1:]:
    mem, recs = load(fn)
    lo, hi = min(mem), max(mem)
    print(f"== {fn.split('/')[-1]}: {len(mem)} bytes, range {lo:#06x}..{hi:#06x}; non-data lines: {recs[:1]} ... {recs[-2:]}")
    # contiguous segments
    segs = []; start = prev = None
    for a in sorted(mem):
        if start is None: start = prev = a
        elif a != prev + 1: segs.append((start, prev)); start = a
        prev = a
    segs.append((start, prev))
    print("   segments:", ", ".join(f"{a:#06x}-{b:#06x}" for a, b in segs))
    base = 0x1C00
    blk = bytes(mem.get(base + i, 0xFF) for i in range(0x60))
    for off in range(0, 0x60, 16):
        print(f"   {base+off:#06x}: " + " ".join(f"{x:02X}" for x in blk[off:off+16]))
