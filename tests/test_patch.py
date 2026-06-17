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
GRAV_CAVE_OFF = P._bin_off(P._file_off(P.GRAV_CAVE_VADDR))
FIREANIM_CAVE_OFF = P._bin_off(P._file_off(P.FIREANIM_CAVE_VADDR))
WATERSCROLL_CAVE_OFF = P._bin_off(P._file_off(P.WATERSCROLL_CAVE_VADDR))
DROPEDGE_CAVE_OFF = P._bin_off(P._file_off(P.DROPEDGE_CAVE_VADDR))
POISON_CAVE_OFF = P._bin_off(P._file_off(P.POISON_CAVE_VADDR))
MENUCAP_OFF_FIX = P._bin_off(P._file_off(P.MENUCAP_VADDR))      # menu flush is patched by address

# Where we drop the search-located signatures (anywhere clear of caves/anchor).
SIGS = {
    "cap": (0x100, P.CAP_SIG), "bob": (0x200, P.BOB_SIG), "walk": (0x300, P.WALK_SIG),
    "turn": (0x400, P.TURN_SIG), "magdelay": (0x500, P.MAGDELAY_SIG),
    "attack": (0x600, P.ATTACK_SIG), "magic": (0x700, P.MAGIC_SIG),
    "swing": (0x800, P.SWING_SIG), "enemyanim": (0x900, P.ENEMYANIM_SIG),
    "enemyanim_far": (0xa00, P.ENEMYANIM_FAR_SIG),
    "turnface": (0xb00, P.TURNFACE_SIG),
    "door_open": (0xc00, P.DOOR_OPEN_SIG), "door_openwin": (0xd00, P.DOOR_OPENWIN_SIG),
    "door_closewin": (0xe00, P.DOOR_CLOSEWIN_SIG), "door_closeramp": (0xf00, P.DOOR_CLOSERAMP_SIG),
    "menu": (0x1000, P.MENU_SIG), "menucap": (MENUCAP_OFF_FIX, P.MENUCAP_SIG),
    "gravity": (0x1200, P.GRAV_SIG), "fireanim": (0x1300, P.FIREANIM_SIG),
    "msg_hold": (0x1500, P.MSG_HOLD_SIG), "msg_appear": (0x1600, P.MSG_APPEAR_SIG),
    "msg_disappear": (0x1700, P.MSG_DISAPPEAR_SIG), "itemspin": (0x1800, P.ITEMSPIN_SIG),
    "item-movein": (0x1900, P.ITEM_IMM_EDITS[0][1]),
    "item-fastspin": (0x1a00, P.ITEM_IMM_EDITS[1][1]),
    "item-moveout": (0x1b00, P.ITEM_IMM_EDITS[2][1]),
    "waterscroll": (0x1400, P.WATERSCROLL_SIG),
    "dropedge": (0x1c00, P.DROPEDGE_SIG),
    "look_up": (0x2100, P.LOOK_UP_SIG), "look_dn": (0x2200, P.LOOK_DN_SIG),
    "poison": (0x2400, P.POISON_SIG),
    "enemydmg": (0x2500, P.ENEMYDMG_SIG),
    "slope": (0x2600, P.SLOPE_SIG),
    "enemy": (ENEMY_OFF, P.ENEMY_JSIG),
}


def make_fixture():
    buf = bytearray(max(MAG_CAVE_OFF, SWING_CAVE_OFF, TURNFACE_CAVE_OFF,
                        GRAV_CAVE_OFF, FIREANIM_CAVE_OFF, WATERSCROLL_CAVE_OFF,
                        DROPEDGE_CAVE_OFF) + 0x400)
    buf[0:8] = b"PS-X EXE"                        # fake GAME.EXE anchor at base 0
    for _, (off, sig) in SIGS.items():
        buf[off:off + len(sig)] = sig
    # two copies of the FOV H-load idiom (the real game has two gte_ldH(200) sites)
    buf[0x1d00:0x1d00 + len(P.FOV_IDIOM)] = P.FOV_IDIOM
    buf[0x1d40:0x1d40 + len(P.FOV_IDIOM)] = P.FOV_IDIOM
    buf[0x1e00:0x1e00 + len(P.CULL_SIG)] = P.CULL_SIG   # PVS cone half-angle site
    buf[0x1f00:0x1f00 + len(P.FOGH_SIG)] = P.FOGH_SIG    # fog calibration H site
    buf[0x2000:0x2000 + len(P.NEARBAND_SIG)] = P.NEARBAND_SIG   # near-band (threshold + cone check)
    buf[0x2300:0x2300 + len(P.BOBFIX_SIG)] = P.BOBFIX_SIG       # head-bob phase block (--bob on/fix)
    return buf


def test_quarter_byte_edits():
    d = make_fixture()
    P.apply_patches(d, "quarter")
    assert d[0x100] == 0x01 and d[0x100 + 0x20] == 0x01            # CAP 4->1
    # BOB default = on (fixed): phase block reordered+scaled at 0x2300; output store left intact
    assert d[0x2300:0x2300 + len(P.BOBFIX_NEW["quarter"])] == P.BOBFIX_NEW["quarter"]
    assert d[0x200 + P.BOB_OFF] == 0x22                            # bob output NOT zeroed (on)
    assert d[0x300 + 4] == 0x83 and d[0x300 + 0x34] == 0x83        # WALK >>0xe
    assert d[0x400 + 0x0c] == 0x08 and d[0x400 + 0x28] == 0x0a     # TURN
    assert d[0x500] == 0xf0                                        # MAGIC-DELAY 60->240
    # ENEMY/NPC anim: nop -> sra v1,v1,2
    assert d[0x900 + 4:0x900 + 8] == P.ENEMYANIM_NEW["quarter"].to_bytes(4, "little")
    # distant (LOD) enemy anim: nop -> sra v1,v1,2
    assert d[0xa00 + 4:0xa00 + 8] == P.ENEMYANIM_FAR_NEW["quarter"].to_bytes(4, "little")
    # doors: open ramp/trigger/window + close window/ramp scaled
    assert d[0xc00 + P.DOOR_OPEN_RAMP_OFF] == 0x08 and d[0xc00 + P.DOOR_OPEN_TRIG_OFF] == 0x7f
    assert d[0xd00 + P.DOOR_OPENWIN_OFF] == 0x80
    assert d[0xe00 + P.DOOR_CLOSEWIN_OFF] == 0xac
    assert d[0xf00 + P.DOOR_CLOSERAMP_OFF] == 0xf8
    assert d[0x1200 + P.GRAV_INC_OFF] == 0x0a        # gravity accel 0x28 -> 0x0a (velocity preserved)
    assert d[0x1500 + P.MSG_HOLD_OFF] == 0x3c        # notification hold 0x0f -> 0x3c (x4)
    assert d[0x1600 + P.MSG_APPEAR_OFF] == 0x05      # notification appear step 0x14 -> 0x05
    assert d[0x1700 + P.MSG_DISAPPEAR_OFF] == 0xfb   # notification disappear step -0x14 -> -0x05
    assert d[0x1800 + P.ITEMSPIN_OFF] == 0x10        # item pickup spin step 0x40 -> 0x10 (÷4)
    for fix_i, fix_off in ((0x1900, 0x0080), (0x1a00, 0x0040), (0x1b00, 0xff80)):
        e = P.ITEM_IMM_EDITS[(0x1900, 0x1a00, 0x1b00).index(fix_i)]
        got = int.from_bytes(d[fix_i + e[2]:fix_i + e[2] + 2], "little")
        assert got == e[4]["quarter"] == fix_off    # item move-in/fast-spin/move-out (÷4)
    assert d[0x1000 + P.MENU_OFF] == 0x08            # menu repeat stays 8 (vblank-paced)
    assert d[0x1000 + P.MENU_VSYNC_OFF:0x1000 + P.MENU_VSYNC_OFF + 4] == \
        P.MENU_VSYNC_NEW.to_bytes(4, "little")       # repeat loop -> deterministic vblank wait
    assert d[MENUCAP_OFF_FIX + P.MENUCAP_OFF:MENUCAP_OFF_FIX + P.MENUCAP_OFF + 4] == \
        P.MENUCAP_NEW.to_bytes(4, "little")          # menu vsync -> vblank cap (this copy only)
    # LOOK (vertical camera): both apply sites addu v1,v0,zero -> sra v1,v0,2 (pitch advance ÷4)
    for look_off in (0x2100, 0x2200):
        assert int.from_bytes(d[look_off + P.LOOK_OFF:look_off + P.LOOK_OFF + 4], "little") == \
            P.LOOK_NEW["quarter"]


def test_half_mode():
    d = make_fixture()
    P.apply_patches(d, "half")
    assert d[0x100] == 0x02                                        # CAP 4->2
    assert d[0x300 + 4] == 0x43                                    # WALK >>0xd
    assert d[0x500] == 0x78                                        # MAGIC-DELAY 60->120
    # ENEMY/NPC anim: nop -> sra v1,v1,1
    assert d[0x900 + 4:0x900 + 8] == P.ENEMYANIM_NEW["half"].to_bytes(4, "little")
    # doors (half): trigger 0x3f, window 0x40, close 0x6c, ramps 0x10/-0x10
    assert d[0xc00 + P.DOOR_OPEN_RAMP_OFF] == 0x10 and d[0xc00 + P.DOOR_OPEN_TRIG_OFF] == 0x3f
    assert d[0xd00 + P.DOOR_OPENWIN_OFF] == 0x40
    assert d[0xe00 + P.DOOR_CLOSEWIN_OFF] == 0x6c and d[0xf00 + P.DOOR_CLOSERAMP_OFF] == 0xf0
    assert d[0x1200 + P.GRAV_INC_OFF] == 0x14                      # gravity accel (half)
    assert d[0x1500 + P.MSG_HOLD_OFF] == 0x1e                      # notification hold (half x2)
    assert d[0x1600 + P.MSG_APPEAR_OFF] == 0x0a                    # notification appear step (half)
    assert d[0x1700 + P.MSG_DISAPPEAR_OFF] == 0xf6                 # notification disappear (half)
    assert d[0x1800 + P.ITEMSPIN_OFF] == 0x20                      # item pickup spin step (half)
    for look_off in (0x2100, 0x2200):                              # LOOK pitch advance ÷2 (sra v1,v0,1)
        assert int.from_bytes(d[look_off + P.LOOK_OFF:look_off + P.LOOK_OFF + 4], "little") == \
            P.LOOK_NEW["half"]
    assert d[0x2300:0x2300 + len(P.BOBFIX_NEW["half"])] == P.BOBFIX_NEW["half"]   # bob phase ÷2


def test_bob_option():
    # default / "on": head-bob fixed (phase block patched), output store left intact
    d = make_fixture()
    P.apply_patches(d, "quarter", bob="on")
    assert d[0x2300:0x2300 + len(P.BOBFIX_NEW["quarter"])] == P.BOBFIX_NEW["quarter"]
    assert d[0x200 + P.BOB_OFF] == 0x22
    # "off": head-bob disabled (output zeroed), phase block left stock
    d2 = make_fixture()
    P.apply_patches(d2, "quarter", bob="off")
    assert d2[0x200 + P.BOB_OFF] == 0x20                            # sh v0 -> sh zero
    assert d2[0x2300:0x2300 + len(P.BOBFIX_SIG)] == P.BOBFIX_SIG    # phase block untouched


def test_cave_redirects_and_bodies():
    d = make_fixture()
    P.apply_patches(d, "quarter")
    assert d[ENEMY_OFF + 8:ENEMY_OFF + 12] == P.ENEMY_JMP.to_bytes(4, "little")
    assert d[0x600 + 0x0c:0x600 + 0x10] == P.ATTACK_JMP.to_bytes(4, "little")
    assert d[0x700 + 0x08:0x700 + 0x0c] == P.MAGIC_JMP.to_bytes(4, "little")
    assert d[0x800 + 0x08:0x800 + 0x0c] == P.SWING_JMP.to_bytes(4, "little")
    assert d[0xb00 + 0x04:0xb00 + 0x08] == P.TURNFACE_JMP.to_bytes(4, "little")
    assert d[0x1200 + P.GRAV_REDIR_OFF:0x1200 + P.GRAV_REDIR_OFF + 4] == \
        P.GRAV_JMP.to_bytes(4, "little")
    assert d[0x1300 + P.FIREANIM_REDIR_OFF:0x1300 + P.FIREANIM_REDIR_OFF + 4] == \
        P.FIREANIM_JMP.to_bytes(4, "little")
    assert d[0x1400 + P.WATERSCROLL_REDIR_OFF:0x1400 + P.WATERSCROLL_REDIR_OFF + 4] == \
        P.WATERSCROLL_JMP.to_bytes(4, "little")
    assert d[0x1c00 + P.DROPEDGE_OFF:0x1c00 + P.DROPEDGE_OFF + 4] == \
        P.DROPEDGE_JMP.to_bytes(4, "little")
    # POISON: tick body redirected to the ÷N cave AND the in-line flash store nopped.
    assert d[0x2400 + P.POISON_REDIR_OFF:0x2400 + P.POISON_REDIR_OFF + 4] == \
        P.POISON_JMP.to_bytes(4, "little")
    assert d[0x2400 + P.POISON_FLASH_OFF:0x2400 + P.POISON_FLASH_OFF + 4] == b"\0\0\0\0"
    for off, words in ((ENEMY_CAVE_OFF, P.ENEMY_CAVE["quarter"]),
                       (ATK_CAVE_OFF, P.ATTACK_CAVE["quarter"]),
                       (MAG_CAVE_OFF, P.MAGIC_CAVE["quarter"]),
                       (SWING_CAVE_OFF, P.SWING_CAVE["quarter"]),
                       (TURNFACE_CAVE_OFF, P.TURNFACE_CAVE["quarter"]),
                       (GRAV_CAVE_OFF, P.GRAV_CAVE["quarter"]),
                       (FIREANIM_CAVE_OFF, P.FIREANIM_CAVE["quarter"]),
                       (WATERSCROLL_CAVE_OFF, P.WATERSCROLL_CAVE["quarter"]),
                       (DROPEDGE_CAVE_OFF, P.DROPEDGE_CAVE["quarter"]),
                       (POISON_CAVE_OFF, P.POISON_CAVE["quarter"])):  # noqa: E501 reordered for load-delay
        got = bytes(d[off:off + 4 * len(words)])
        exp = b"".join(w.to_bytes(4, "little") for w in words)
        assert got == exp


def test_fov_optional():
    # no --fov: H immediates untouched
    d = make_fixture()
    P.apply_patches(d, "quarter")
    assert d[0x1d00:0x1d00 + 2] == P.FOV_H_DEFAULT.to_bytes(2, "little")
    assert d[0x1d40:0x1d40 + 2] == P.FOV_H_DEFAULT.to_bytes(2, "little")
    # --fov 90 -> H=160, patched at BOTH sites
    d = make_fixture()
    P.apply_patches(d, "quarter", fov=90.0)
    assert P._fov_to_h(90.0) == 160
    assert d[0x1d00:0x1d00 + 2] == (160).to_bytes(2, "little")
    assert d[0x1d40:0x1d40 + 2] == (160).to_bytes(2, "little")
    # rest of the idiom (move t4,t0 / ctc2 t4,H) is preserved
    assert d[0x1d00 + 4:0x1d00 + len(P.FOV_IDIOM)] == P.FOV_IDIOM[4:]
    # culling cone widened too (auto-on with --fov); stock half-angle 0x1b8 -> wider
    cull = P._fov_to_cull_half(90.0)
    assert cull > P.CULL_STOCK
    assert d[0x1e00 + P.CULL_OFF:0x1e00 + P.CULL_OFF + 2] == cull.to_bytes(2, "little")
    # fog H recalibrated to match the render H (=160 at 90 deg)
    assert d[0x1f00 + P.FOGH_OFF:0x1f00 + P.FOGH_OFF + 2] == (160).to_bytes(2, "little")
    # near band: threshold widened + both cone-check branches NOPed
    assert d[0x2000 + P.NEARBAND_THRESH_OFF] == P.NEARBAND_THRESH_NEW
    assert d[0x2000 + P.NEARBAND_NOP1_OFF:0x2000 + P.NEARBAND_NOP1_OFF + 4] == bytes(4)
    assert d[0x2000 + P.NEARBAND_NOP2_OFF:0x2000 + P.NEARBAND_NOP2_OFF + 4] == bytes(4)
    # the cull cone stays AT/ABOVE the 0x258 limiter so it's always cos-scaled (no pitch-cross flicker)
    assert P._fov_to_cull_half(P.CULL_STOCK_FOV) >= P.CULL_LIMITER
    assert P._fov_to_cull_half(90.0) >= P.CULL_LIMITER
    # without --fov (and no --cull) culling + fog are untouched
    d2 = make_fixture()
    P.apply_patches(d2, "quarter")
    assert d2[0x1e00 + P.CULL_OFF:0x1e00 + P.CULL_OFF + 2] == P.CULL_STOCK.to_bytes(2, "little")
    assert d2[0x1f00 + P.FOGH_OFF:0x1f00 + P.FOGH_OFF + 2] == P.FOGH_STOCK.to_bytes(2, "little")
    assert d2[0x2000 + P.NEARBAND_THRESH_OFF] == 0x05
    # --cull on without --fov: culling applied (stock-FOV cone), fog untouched (H unchanged)
    d3 = make_fixture()
    P.apply_patches(d3, "quarter", cull=True)
    assert d3[0x1e00 + P.CULL_OFF:0x1e00 + P.CULL_OFF + 2] == \
        P._fov_to_cull_half(P.CULL_STOCK_FOV).to_bytes(2, "little")
    assert d3[0x1f00 + P.FOGH_OFF:0x1f00 + P.FOGH_OFF + 2] == P.FOGH_STOCK.to_bytes(2, "little")
    # --cull off with --fov: FOV applied, culling skipped
    d4 = make_fixture()
    P.apply_patches(d4, "quarter", fov=90.0, cull=False)
    assert d4[0x1d00:0x1d00 + 2] == (160).to_bytes(2, "little")
    assert d4[0x1e00 + P.CULL_OFF:0x1e00 + P.CULL_OFF + 2] == P.CULL_STOCK.to_bytes(2, "little")


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
