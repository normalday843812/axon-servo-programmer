import sys, re
b = open(sys.argv[1], 'rb').read()
minlen = int(sys.argv[2]) if len(sys.argv) > 2 else 4
seen = set()
for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}' % minlen, b):
    s = m.group().decode('utf-16le')
    if s not in seen:
        seen.add(s)
        print(f"{m.start():#09x} {s}")
