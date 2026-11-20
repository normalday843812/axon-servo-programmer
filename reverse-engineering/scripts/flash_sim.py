"""Simulated-bootloader test: compare axon.flash() packets with an independent
transliteration of the official app's btnUPF_Click loop."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))   # repo root
import axon

def official_packets(lines, seed):
    """Direct port of the decompiled C# (array indices as in the original)."""
    out = []
    array = [0] * 64
    for text in lines[1:]:
        if "$" in text:
            array[0], array[1], array[2], array[3] = 4, 130, 22, 10
            array[4] = int(text[1:3], 16); array[5] = int(text[3:5], 16)
            for n in range(6, 64): array[n] = 0xEE          # "random"
            plain = list(array)
            for i in range(3, 25): array[i] ^= seed[i - 3]
            out.append(("erase", plain[:6], list(array), 85))
        if ":" in text and text[7:9] == "00":
            array[0], array[1], array[2], array[3] = 4, 130, 22, 58
            b3 = 0
            for k in range((len(text) - 1) // 2):
                array[k + 4] = int(text[k * 2 + 1:k * 2 + 3], 16); b3 = array[k + 4]
            if array[4] + 5 < 22:
                for j in range(array[4] + 5 + 4, 64): array[j] = 0xEE
            plain = list(array)
            for i in range(3, 25): array[i] ^= seed[i - 3]
            out.append(("write", plain[:array[4] ^ 0 if False else plain[4] + 9], list(array), b3))
    return out

class FakeProg:
    KEYREPLY = bytes(range(0x40, 0x40 + 22))
    def __init__(self, fail_once_at=None):
        self.sent = []; self.seed = None; self.exited = False; self.fail_once_at = fail_once_at; self.n = 0
        self.source = 2                      # starts in joystick mode, like the real programmer
    def status(self):
        return {"source": self.source}
    def ppm_disable(self):
        self.source = 0
    def xfer(self, payload, **kw):
        if 0x80 <= payload[0] <= 0x83:
            assert self.source == 0, "bootloader command sent while the signal output is on"
        pkt = bytes([4]) + bytes(payload); pkt += bytes(64 - len(pkt))
        r = bytearray(64); r[0] = 4; r[1] = 1
        cmd = pkt[1]
        if cmd == 0x80:
            assert pkt[:7] == bytes([4, 0x80, 4, 1, 2, 3, 4]), pkt[:8].hex()
            r[5:9] = b"V1.4"; r[9], r[10] = 0x08, 0x22
        elif cmd == 0x81:
            assert pkt[2] == 22
            r[5:27] = self.KEYREPLY
            self.seed = bytes(pkt[3 + i] ^ self.KEYREPLY[i] for i in range(22))
        elif cmd == 0x82:
            self.n += 1
            if self.fail_once_at == self.n:
                self.fail_once_at = None
                return None                                  # simulate a lost reply
            plain = bytearray(pkt)
            for i in range(22): plain[3 + i] ^= self.seed[i]
            self.sent.append((bytes(plain), pkt))
            assert pkt[2] == 22
            if plain[3] == 0x0A: r[5] = 0x55
            elif plain[3] == 0x3A:
                n = plain[4]; rec = plain[4:4 + n + 5]
                assert sum(rec) & 0xFF == 0, "bad record checksum reached the bootloader"
                r[5] = rec[-1]
            else: raise AssertionError("unknown boot data kind")
        elif cmd == 0x83:
            assert pkt[:8] == bytes([4, 0x83, 22, 0, 0, 0xFF, 0x55, 0xAA]), pkt[:8].hex()
            self.exited = True
        return bytes(r)

ok = True
for f in sys.argv[1:]:
    fw = axon.Firmware(f)
    raw = open(f, "rb").read()
    text = axon.aes128_cbc_decrypt(axon.SFM_KEY, bytes(16), raw[16:]).decode("latin1")
    lines = text.replace("\r\n", "\n").split("\n")
    for fail_at in (None, 7, 200):
        fp = FakeProg(fail_once_at=fail_at)
        ver = axon.flash(fp, fw, expect_model=fw.model)
        ref = official_packets(lines, fp.seed)
        # a retried packet appears once in fp.sent because the lost one was never recorded
        good = len(ref) == len(fp.sent) and fp.exited and ver == "V1.4"
        mism = 0
        for (kind, plain_ref, enc_ref, want), (plain_mine, enc_mine) in zip(ref, fp.sent):
            n = len(plain_ref)
            if bytes(plain_ref) != plain_mine[:n] or len(enc_mine) != 64:
                mism += 1
            # masked region must be exactly bytes 3..24, bytes 0..2 in clear
            if enc_mine[:3] != bytes([4, 0x82, 22]): mism += 1
        ok &= good and mism == 0
        print(f"{os.path.basename(f):32s} lost-reply-at={fail_at!s:5} packets={len(fp.sent)} ref={len(ref)} mismatches={mism} exit_sent={fp.exited} -> {'OK' if good and mism == 0 else 'FAIL'}")
# wrong-model and wrong-id guards
fw = axon.Firmware(sys.argv[1])
for label, kwargs, patch in (("wrong model", {"expect_model": "MINIMK2"}, None), ("wrong boot id", {"expect_model": fw.model}, 0x99)):
    fp = FakeProg()
    if patch:
        orig = fp.xfer
        def x(payload, _o=orig, **kw):
            r = bytearray(_o(payload, **kw));
            if payload[0] == 0x80: r[9] = patch
            return bytes(r)
        fp.xfer = x
    try:
        axon.flash(fp, fw, **kwargs); print(label, "NOT REJECTED"); ok = False
    except axon.AxonError as e:
        print(f"{label}: rejected before any erase ({len(fp.sent)} data packets sent): {e}")
        ok &= len(fp.sent) == 0
print("ALL OK" if ok else "FAILURES")
