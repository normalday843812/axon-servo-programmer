import sys, re, base64, os
src, outdir, pat = sys.argv[1], sys.argv[2], sys.argv[3]
txt = open(src, encoding='utf-8', errors='replace').read()
for m in re.finditer(r'<data name="([^"]+)"[^>]*>\s*<value>(.*?)</value>', txt, re.S):
    name, val = m.group(1), m.group(2)
    if not re.search(pat, name):
        continue
    try:
        raw = base64.b64decode(val)
    except Exception as e:
        print("skip", name, e); continue
    # find an image signature inside the serialized blob
    for sig, ext in ((b'\x89PNG\r\n\x1a\n', 'png'), (b'\xff\xd8\xff', 'jpg'), (b'BM', 'bmp')):
        i = raw.find(sig)
        if i >= 0:
            fn = os.path.join(outdir, re.sub(r'[^A-Za-z0-9_.-]', '_', name) + '.' + ext)
            open(fn, 'wb').write(raw[i:])
            print(name, len(raw), '->', fn)
            break
    else:
        print(name, len(raw), 'no image sig', raw[:16])
