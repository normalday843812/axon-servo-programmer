import sys
def load(fn):
    mem = {}
    for line in open(fn, 'rb').read().replace(b'\x00', b'').decode('ascii', 'replace').splitlines():
        line = line.strip()
        if line.startswith(':'):
            b = bytes.fromhex(line[1:])
            if b[3] == 0:
                for i in range(b[0]): mem[((b[1] << 8) | b[2]) + i] = b[4 + i]
    return mem
for fn in sys.argv[1:]:
    mem = load(fn)
    name = fn.split('/')[-1]
    print("==", name)
    addrs = sorted(mem)
    data = bytes(mem[a] for a in addrs)
    # look for id-like sequences: 34 ?? 22 08, and x 22 08
    for i in range(len(data) - 3):
        if data[i + 1] == 0x22 and data[i + 2] == 0x08 and addrs[i + 2] == addrs[i] + 2:
            ctx = data[max(0, i - 6): i + 8]
            print(f"   {addrs[i]:#06x}: ..{ctx.hex(' ')}")
    seg = bytes(mem.get(a, 0xFF) for a in range(0x1AF0, 0x1B40))
    print("   0x1af0:", seg[:16].hex(' '))
    print("   0x1b00:", seg[16:32].hex(' '))
    print("   0x1b10:", seg[32:48].hex(' '))
