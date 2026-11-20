"""Read-only probe of the Axon MK2 programmer. Sends only query commands."""
import sys
import time
import hid

VID, PID = 0x0473, 0x13AA


def hx(b, n=None):
    b = bytes(b if n is None else b[:n])
    return " ".join(f"{x:02X}" for x in b)


def xfer(dev, payload, timeout=400, expect4=None, tries=3, label=""):
    pkt = bytes(payload) + bytes(64 - len(payload))
    dev.write(pkt)
    for _ in range(tries):
        r = bytes(dev.read(64, timeout))
        if not r:
            print(f"  [{label}] timeout")
            return None
        if expect4 is not None and r[4] != expect4:
            print(f"  [{label}] unexpected (r[4]={r[4]:02X}), rereading: {hx(r, 16)}")
            continue
        return r
    return None


def main():
    dev = hid.device()
    dev.open(VID, PID)
    try:
        print("product:", dev.get_product_string(), "| mfr:", dev.get_manufacturer_string())

        # drain anything pending
        dev.set_nonblocking(1)
        while dev.read(64):
            pass
        dev.set_nonblocking(0)

        print("\n> 04 91 (identify adapter)")
        r = xfer(dev, [0x04, 0x91], label="91")
        print("  <", hx(r) if r else None)

        print("\n> 04 AF (adapter status)")
        r = xfer(dev, [0x04, 0xAF], timeout=100, expect4=0xAF, label="AF")
        if r:
            print("  <", hx(r, 32))
            volts = (r[9] * 256 + r[10]) / 4096 * 3.3 * 5.99
            amps = (r[13] * 256 + r[14]) / 4096 * 3.3 / 0.6
            print(f"  mode={r[15]} power_state={r[16]} volts={volts:.2f} amps={amps:.3f} "
                  f"ppm_out={r[5]*256+r[6]} ppm_in_flag={r[19]}")

        print("\n> 04 8A 00 00 04 (detect servo)")
        r = xfer(dev, [0x04, 0x8A, 0x00, 0x00, 0x04], expect4=0x8A, label="8A")
        print("  <", hx(r, 32) if r else None)
        servo_ok = bool(r) and r[1] == 1

        if servo_ok:
            print("\n> 04 CD 00 00 3B (read 59-byte parameter block)")
            r = xfer(dev, [0x04, 0xCD, 0x00, 0x00, 59], expect4=59, label="CD")
            print("  <", hx(r) if r else None)
        else:
            print("\nservo not detected; skipping parameter read")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
