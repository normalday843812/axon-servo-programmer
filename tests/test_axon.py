"""Tests that need neither a programmer nor any Axon file.

    python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import axon  # noqa: E402

# Factory parameter block of a MAX MK2 in Servo mode, as read from a servo.
FACTORY = bytes.fromhex(
    "3E781948F02FFF78FAFAFFDCCA73523468" "9CDC0A2290" "0000" "1200" "010014001400"
    "303030302A2A2A2A2A2A2A2A" "140819" "4D41584D4B322A2A2A2A2A2A")


def changed(old, new):
    return {i for i in range(len(old)) if old[i] != new[i]}


class AesTests(unittest.TestCase):
    def test_fips197_block(self):
        pt = axon.aes128_cbc_decrypt(bytes(range(16)), bytes(16),
                                     bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"))
        self.assertEqual(pt.hex(), "00112233445566778899aabbccddeeff")

    def test_sp800_38a_cbc(self):
        pt = axon.aes128_cbc_decrypt(
            bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c"), bytes(range(16)),
            bytes.fromhex("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"))
        self.assertEqual(pt.hex(), "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")

    def test_rejects_partial_blocks(self):
        with self.assertRaises(ValueError):
            axon.aes128_cbc_decrypt(bytes(16), bytes(16), bytes(17))


class SettingsTests(unittest.TestCase):
    def test_block_is_59_bytes(self):
        self.assertEqual(len(FACTORY), axon.BLOCK_LEN)

    def test_decode_factory_block(self):
        d = axon.decode(FACTORY, "servo")
        self.assertEqual(d, {
            "left": "250", "right": "250", "neutral": "0", "damping": "120", "power": "100.0%",
            "sensitivity": "ultra-high", "inversion": "off", "soft-start": "11",
            "lose-ppm": "release", "ol1-level": "79.2%", "ol1-time": "4.0s",
            "ol2-level": "45.1%", "ol2-time": "8.0s", "ol3-level": "32.2%", "ol3-time": "12.0s",
            "signal": "normal", "beep": "on", "name": "0000", "min-power": "120", "sys-amp": "62",
        })
        self.assertEqual(axon.model_name(FACTORY), "MAXMK2")
        self.assertEqual(axon.made_date(FACTORY), "2025-08-20")

    def set(self, mode="servo", advanced=False, **kw):
        return axon.apply_changes(FACTORY, mode, {k.replace("_", "-"): v for k, v in kw.items()}, advanced)

    def test_each_setting_lands_on_its_byte(self):
        cases = [
            (dict(left="120"), {9: 120}), (dict(right="30"), {8: 30}),
            (dict(neutral="-3"), {22: 0xFD, 23: 0xFF}), (dict(damping="200"), {1: 200}),
            (dict(power="50%"), {6: 127}), (dict(sensitivity="low"), {2: 150}),
            (dict(sensitivity="medium"), {2: 100}), (dict(inversion="on"), {20: 0x23}),
            (dict(soft_start="3"), {10: 3}), (dict(lose_ppm="keep"), {20: 0x62}),
            (dict(lose_ppm="neutral"), {20: 0x6A}), (dict(ol1_level="50"), {12: 127}),
            (dict(ol2_time="5s"), {16: 64}), (dict(signal="sanwa-sr"), {20: 0xA2}),
            (dict(signal="futaba-ur"), {20: 0xA2, 18: 143}), (dict(signal="futaba-sr"), {20: 0x32}),
            (dict(beep="off"), {26: 0}), (dict(name="TEAM"), {32: 0x54, 33: 0x45, 34: 0x41, 35: 0x4D}),
        ]
        for kw, expect in cases:
            with self.subTest(kw=kw):
                new = self.set(**kw)
                self.assertEqual(changed(FACTORY, new), set(expect), "only the intended bytes may change")
                for off, val in expect.items():
                    self.assertEqual(new[off], val)

    def test_soft_start_level_11_is_ff(self):
        new = axon.apply_changes(self.set(soft_start="5"), "servo", {"soft-start": "11"}, False)
        self.assertEqual(new[10], 0xFF)

    def test_changes_can_be_undone_exactly(self):
        new = self.set(left="100", right="100", inversion="on", neutral="7", lose_ppm="neutral",
                       signal="futaba-ur", name="X", sensitivity="low", beep="off")
        back = axon.apply_changes(bytes(new), "servo", {
            "left": "250", "right": "250", "inversion": "off", "neutral": "0", "lose-ppm": "release",
            "signal": "normal", "name": "0000", "sensitivity": "ultra-high", "beep": "on"}, False)
        self.assertEqual(bytes(back), FACTORY)

    def test_identity_bytes_are_never_touched(self):
        new = self.set(name="ABCDEFGHIJKL", left="10", power="10")
        self.assertEqual(new[44:], FACTORY[44:])

    def test_bad_values_are_rejected(self):
        for kw in (dict(left="5"), dict(left="256"), dict(left="12.5"), dict(neutral="26"),
                   dict(power="150"), dict(power="abc"), dict(sensitivity="max"),
                   dict(inversion="maybe"), dict(soft_start="12"), dict(lose_ppm="explode"),
                   dict(ol1_time="11"), dict(signal="spektrum"), dict(name="thirteen chars"),
                   dict(name="caf\u00e9"), dict(bogus="1")):
            with self.subTest(kw=kw), self.assertRaises(axon.AxonError):
                self.set(**kw)

    def test_hidden_values_need_advanced(self):
        with self.assertRaises(axon.AxonError):
            self.set(min_power="100")
        self.assertEqual(self.set(advanced=True, min_power="100")[7], 100)

    def test_cr_mode_exposes_only_its_four_settings(self):
        self.assertEqual(list(axon.decode(FACTORY, "cr")), ["power", "inversion", "proptl", "beep"])
        self.assertEqual(self.set(mode="cr", proptl="3.0")[15], 30)
        with self.assertRaises(axon.AxonError):
            self.set(mode="cr", left="100")

    def test_copy_is_lossless(self):
        src = bytearray(self.set(left="33", right="44", neutral="-9", lose_ppm="keep", name="SRC",
                                 ol3_level="55", signal="futaba-ur", inversion="on"))
        src[17] = 0x9B                      # a time value that does not survive text rounding
        dst = bytearray(FACTORY)
        for s in axon.SERVO_SETTINGS:
            if not s.advanced:
                s.copy(src, dst)
        self.assertEqual(dst[:axon.WRITE_LEN], src[:axon.WRITE_LEN])

    def test_svp_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.svp")
            with open(path, "wb") as f:
                f.write(axon.svp_bytes(FACTORY))
            self.assertEqual(os.path.getsize(path), 95)
            self.assertEqual(axon.svp_load(path), FACTORY)
            with open(path, "wb") as f:
                f.write(b"not a settings file")
            with self.assertRaises(axon.AxonError):
                axon.svp_load(path)


class FakeProgrammer:
    """Stands in for the programmer + a servo bootloader. Insists on the rules that
    matter on real hardware: signal output off, and nothing but boot commands in a session."""
    KEY = bytes(range(0x40, 0x56))

    def __init__(self, source=2, boot_ok=True, echo_seed=False, ids=(0x08, 0x22), lose_reply_at=None):
        self.source, self.boot_ok, self.echo_seed, self.ids = source, boot_ok, echo_seed, ids
        self.lose_reply_at = lose_reply_at
        self.in_session = False
        self.seed = None
        self.data = []          # un-masked boot data bodies, in order
        self.exited = False
        self.count = 0

    def status(self):
        assert not self.in_session, "status request inside a bootloader session"
        return {"source": self.source}

    def ppm_disable(self):
        self.source = 0

    def xfer(self, payload, **kw):
        pkt = bytes([4]) + bytes(payload)
        pkt += bytes(64 - len(pkt))
        cmd = pkt[1]
        assert 0x80 <= cmd <= 0x83, "non-boot command sent to the fake"
        assert self.source == 0, "bootloader command while the signal output is on"
        r = bytearray(64)
        r[0], r[1] = 4, 1
        if cmd == 0x80:
            self.in_session = True
            if not self.boot_ok:
                r[1] = 0
                return bytes(r)
            r[5:9] = b"V0.3"
            r[9], r[10] = self.ids
        elif cmd == 0x81:
            if self.echo_seed:
                r[3:25] = pkt[3:25]
            else:
                r[5:27] = self.KEY
                self.seed = bytes(pkt[3 + i] ^ self.KEY[i] for i in range(22))
        elif cmd == 0x82:
            self.count += 1
            if self.lose_reply_at == self.count:
                self.lose_reply_at = None
                return None
            body = bytes(pkt[3 + i] ^ self.seed[i] for i in range(22))
            self.data.append(body)
            if body[0] == 0x0A:
                r[5] = 0x55
            else:
                rec = body[1:1 + body[1] + 5]
                assert sum(rec) & 0xFF == 0, "corrupt hex record reached the bootloader"
                r[5] = rec[-1]
        elif cmd == 0x83:
            assert pkt[:8] == bytes([4, 0x83, 22, 0, 0, 0xFF, 0x55, 0xAA])
            self.in_session = False
            self.exited = True
        return bytes(r)


def hex_record(addr, data):
    body = bytes([len(data), addr >> 8, addr & 0xFF, 0]) + bytes(data)
    return body + bytes([(-sum(body)) & 0xFF])


def fake_firmware(model="MAXMK2", ids=(0x08, 0x22)):
    recs = [hex_record(0x0400, range(16)), hex_record(0x0410, range(16, 32)), hex_record(0x0420, [1, 2, 3])]
    steps = [("erase", (0x04, 0x00)), ("erase", (0x06, 0x00))] + [("write", r) for r in recs]
    return types.SimpleNamespace(model=model, id1=ids[0], id2=ids[1], steps=steps), recs


class FlashTests(unittest.TestCase):
    def test_full_session(self):
        fw, recs = fake_firmware()
        prog = FakeProgrammer(source=2)
        seen = []
        version = axon.flash(prog, fw, expect_model="MAXMK2", progress=lambda n, t: seen.append((n, t)))
        self.assertEqual(version, "V0.3")
        self.assertEqual(prog.source, 0, "signal output must be switched off first")
        self.assertTrue(prog.exited)
        self.assertEqual([d[:3] for d in prog.data[:2]], [bytes([0x0A, 4, 0]), bytes([0x0A, 6, 0])])
        for body, rec in zip(prog.data[2:], recs):
            self.assertEqual(body[0], 0x3A)
            self.assertEqual(body[1:1 + len(rec)], rec)
        self.assertEqual(seen[-1], (5, 5))

    def test_lost_reply_is_retried(self):
        fw, _ = fake_firmware()
        prog = FakeProgrammer(lose_reply_at=3)
        axon.flash(prog, fw, expect_model="MAXMK2")
        self.assertEqual(len(prog.data), 5)
        self.assertTrue(prog.exited)

    def assert_refused_before_erasing(self, prog, fw, **kw):
        with self.assertRaises(axon.AxonError):
            axon.flash(prog, fw, **kw)
        self.assertEqual(prog.data, [], "nothing may be erased or written")

    def test_wrong_model_is_refused(self):
        fw, _ = fake_firmware(model="MINIMK2")
        self.assert_refused_before_erasing(FakeProgrammer(), fw, expect_model="MAXMK2")

    def test_wrong_bootloader_id_is_refused(self):
        fw, _ = fake_firmware()
        prog = FakeProgrammer(ids=(0x09, 0x22))
        self.assert_refused_before_erasing(prog, fw, expect_model="MAXMK2")
        self.assertTrue(prog.exited)

    def test_silent_bootloader_is_refused(self):
        fw, _ = fake_firmware()
        self.assert_refused_before_erasing(FakeProgrammer(boot_ok=False), fw, expect_model="MAXMK2")
        self.assert_refused_before_erasing(FakeProgrammer(echo_seed=True), fw, expect_model="MAXMK2")


if __name__ == "__main__":
    unittest.main()
