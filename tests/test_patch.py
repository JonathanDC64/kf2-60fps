"""Tests for build_60fps_patch -- run against a SYNTHETIC fixture only.

No copyrighted game data is used. The fixture is a zero blob with the code
signatures placed at the offsets the patcher expects (the enemy jump signature
at the offset that makes the GAME.EXE cave-offset math resolve to a fake
"PS-X EXE" anchor at byte 0), so we can exercise every patch + the BPS encoder.
"""
import os
import sys
import zlib

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import build_60fps_patch as P  # noqa: E402

# Offset of the enemy jump signature that makes `base` (GAME.EXE byte 0) land at 0.
ENEMY_OFF = P._bin_off(P._file_off(P.ENEMY_JSIG_VADDR))          # 0x46510
ENEMY_CAVE_OFF = P._bin_off(P._file_off(P.CAVE_VADDR))          # 0x7ECC0
ATK_CAVE_OFF = P._bin_off(P._file_off(P.ATK_CAVE_VADDR))
MAG_CAVE_OFF = P._bin_off(P._file_off(P.MAG_CAVE_VADDR))
SWING_CAVE_OFF = P._bin_off(P._file_off(P.SWING_CAVE_VADDR))
TURNFACE_CAVE_OFF = P._bin_off(P._file_off(P.TURNFACE_CAVE_VADDR))

# Where we drop the search-located signatures (anywhere clear of caves/anchor).
SIGS = {
    "cap": (0x100, P.CAP_SIG), "bob": (0x200, P.BOB_SIG), "walk": (0x300, P.WALK_SIG),
    "turn": (0x400, P.TURN_SIG), "magdelay": (0x500, P.MAGDELAY_SIG),
    "attack": (0x600, P.ATTACK_SIG), "magic": (0x700, P.MAGIC_SIG),
    "swing": (0x800, P.SWING_SIG), "enemyanim": (0x900, P.ENEMYANIM_SIG),
    "enemyanim_far": (0xa00, P.ENEMYANIM_FAR_SIG),
    "turnface": (0xb00, P.TURNFACE_SIG),
    "enemy": (ENEMY_OFF, P.ENEMY_JSIG),
}


def make_fixture():
    buf = bytearray(max(MAG_CAVE_OFF, SWING_CAVE_OFF, TURNFACE_CAVE_OFF) + 0x400)   # fit highest cave
    buf[0:8] = b"PS-X EXE"                        # fake GAME.EXE anchor at base 0
    for _, (off, sig) in SIGS.items():
        buf[off:off + len(sig)] = sig
    return buf


def test_quarter_byte_edits():
    d = make_fixture()
    P.apply_patches(d, "quarter")
    assert d[0x100] == 0x01 and d[0x100 + 0x20] == 0x01            # CAP 4->1
    assert d[0x200 + P.BOB_OFF] == 0x20                            # BOB
    assert d[0x300 + 4] == 0x83 and d[0x300 + 0x34] == 0x83        # WALK >>0xe
    assert d[0x400 + 0x0c] == 0x08 and d[0x400 + 0x28] == 0x0a     # TURN
    assert d[0x500] == 0xf0                                        # MAGIC-DELAY 60->240
    # ENEMY/NPC anim: nop -> sra v1,v1,2
    assert d[0x900 + 4:0x900 + 8] == P.ENEMYANIM_NEW["quarter"].to_bytes(4, "little")
    # distant (LOD) enemy anim: nop -> sra v1,v1,2
    assert d[0xa00 + 4:0xa00 + 8] == P.ENEMYANIM_FAR_NEW["quarter"].to_bytes(4, "little")


def test_half_mode():
    d = make_fixture()
    P.apply_patches(d, "half")
    assert d[0x100] == 0x02                                        # CAP 4->2
    assert d[0x300 + 4] == 0x43                                    # WALK >>0xd
    assert d[0x500] == 0x78                                        # MAGIC-DELAY 60->120
    # ENEMY/NPC anim: nop -> sra v1,v1,1
    assert d[0x900 + 4:0x900 + 8] == P.ENEMYANIM_NEW["half"].to_bytes(4, "little")


def test_cave_redirects_and_bodies():
    d = make_fixture()
    P.apply_patches(d, "quarter")
    assert d[ENEMY_OFF + 8:ENEMY_OFF + 12] == P.ENEMY_JMP.to_bytes(4, "little")
    assert d[0x600 + 0x0c:0x600 + 0x10] == P.ATTACK_JMP.to_bytes(4, "little")
    assert d[0x700 + 0x08:0x700 + 0x0c] == P.MAGIC_JMP.to_bytes(4, "little")
    assert d[0x800 + 0x08:0x800 + 0x0c] == P.SWING_JMP.to_bytes(4, "little")
    assert d[0xb00 + 0x04:0xb00 + 0x08] == P.TURNFACE_JMP.to_bytes(4, "little")
    for off, words in ((ENEMY_CAVE_OFF, P.ENEMY_CAVE["quarter"]),
                       (ATK_CAVE_OFF, P.ATTACK_CAVE["quarter"]),
                       (MAG_CAVE_OFF, P.MAGIC_CAVE["quarter"]),
                       (SWING_CAVE_OFF, P.SWING_CAVE["quarter"]),
                       (TURNFACE_CAVE_OFF, P.TURNFACE_CAVE["quarter"])):
        got = bytes(d[off:off + 4 * len(words)])
        exp = b"".join(w.to_bytes(4, "little") for w in words)
        assert got == exp


def test_missing_signature_errors():
    with pytest.raises(SystemExit):
        P.apply_patches(bytearray(0x90000), "quarter")            # all zeros -> no sigs


def _apply_bps(source, bps):
    """Minimal BPS applier (SourceRead + TargetRead only) for the round-trip test."""
    assert bps[:4] == b"BPS1"
    pos = 4

    def rv():
        nonlocal pos
        n, shift = 0, 0
        while True:
            x = bps[pos]
            pos += 1
            n += (x & 0x7f) << shift
            if x & 0x80:
                return n
            shift += 7
            n += 1 << shift

    rv()  # source size
    tlen = rv()
    rv()  # metadata size
    out = bytearray()
    while len(out) < tlen:
        cmd = rv()
        mode, length = cmd & 3, (cmd >> 2) + 1
        if mode == 0:                                             # SourceRead
            out += source[len(out):len(out) + length]
        elif mode == 1:                                           # TargetRead
            out += bps[pos:pos + length]
            pos += length
        else:
            raise AssertionError("unexpected BPS mode %d" % mode)
    return bytes(out)


def test_bps_roundtrip():
    src = make_fixture()
    tgt = bytearray(src)
    P.apply_patches(tgt, "quarter")
    bps = P.make_bps(bytes(src), bytes(tgt))
    assert bps[:4] == b"BPS1"
    # footer source CRC must match the real source
    src_crc = int.from_bytes(bps[-12:-8], "little")
    assert src_crc == (zlib.crc32(bytes(src)) & 0xffffffff)
    # applying the patch to the source must reproduce the target
    assert _apply_bps(bytes(src), bps) == bytes(tgt)
