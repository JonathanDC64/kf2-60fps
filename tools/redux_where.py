#!/usr/bin/env python3
"""One-shot: pause the emulator and report PC, RA, SP, and code-address words on
the stack (the call chain) -- to locate a blocking loop (e.g. the menu loop)."""
import socket, struct, time, urllib.request


def web(fn):
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://localhost:8080/api/v1/execution-flow?function=%s" % fn,
            method="POST", data=b""), timeout=5).read()
    except Exception as e:
        print("web", fn, e)


class Gdb:
    def __init__(s):
        s.s = socket.create_connection(("127.0.0.1", 3333), timeout=20); s.s.settimeout(20)

    def send(s, b):
        ck = sum(b.encode()) & 0xff; s.s.sendall(("$%s#%02x" % (b, ck)).encode())

    def recv_pkt(s):
        buf = b""
        while True:
            c = s.s.recv(4096)
            if not c:
                return None
            buf += c
            if buf.count(b"#") > 0 and len(buf.split(b"#")[-1]) >= 2:
                try:
                    return buf[buf.index(b"$") + 1:buf.rindex(b"#")].decode("latin1")
                finally:
                    s.s.sendall(b"+")

    def cmd(s, b):
        s.send(b); return s.recv_pkt()


def main():
    g = Gdb()
    web("pause"); time.sleep(0.2)
    g.s.sendall(b"\x03"); time.sleep(0.1)
    try:
        g.s.recv(4096)
    except Exception:
        pass
    r = g.cmd("g")
    regs = [struct.unpack("<I", bytes.fromhex(r[i:i + 8]))[0] for i in range(0, 38 * 8, 8)]
    pc, ra, sp = regs[37], regs[31], regs[29]
    print("PC=%08X  RA=%08X  SP=%08X" % (pc, ra, sp))
    stk = bytes.fromhex(g.cmd("m%x,%x" % (sp, 0x200)))
    print("code-address words on stack (likely return addresses / call chain):")
    seen = []
    for i in range(0, len(stk), 4):
        v = struct.unpack_from("<I", stk, i)[0]
        if 0x80010000 <= v < 0x80090000 and v not in seen:
            seen.append(v)
            print("  sp+0x%03x = %08X" % (i, v))
    web("resume")


if __name__ == "__main__":
    main()
