#!/usr/bin/env python3
"""King's Field II (USA, SLUS-00255) 60 fps speed-compensation patcher.

KF2 advances its game logic once per *rendered frame* and the display is
vblank-locked, so the original is hard-capped at ~15 fps. With enough emulator
CPU overclock the game can render at 60 fps, but then every per-frame system
runs ~4x too fast. This patcher raises the frame cap to 60 fps and scales the
per-frame systems back down so the game plays at native speed at 60 fps --
portable across any sufficient overclock value (the cap prevents exceeding it).

It operates on a raw MODE2/2352 .bin of the disc, locating each site by code
signature (so it is robust to small layout differences) and either making
same-size byte edits or redirecting a single instruction into a code cave
placed in unused inter-function padding inside GAME.EXE. No game code is
shipped with this tool; you supply your own legally-obtained dump.

Systems patched (mode `quarter` = 60 fps + 1/4 speed; `half` = 30 fps + 1/2):
  CAP         frame cap 4 vblanks/frame -> 1 (60 fps) / 2 (30 fps)
  BOB         cosmetic head-bob disabled
  WALK/TURN   player move + turn speed /N
  ENEMY       enemy movement speed /N (round-half-away cave)
  ATTACK-BAR  weapon-charge recharge /N (frame-gate cave)
  MAGIC       magic-stamina gauge fill /N (self-counter frame-gate cave)
  MAGIC-DELAY magic recharge delay xN (so it starts with the attack bar)

Usage:
  build_60fps_patch.py <input.bin> <output.bin> [--mode quarter|half]
                       [--bps patch.bps] [--no-crc-check]
See docs/RESEARCH.md for the full reverse-engineering write-up.
"""
import argparse
import sys
import zlib

# Reference fingerprint of the known-good source (Redump "King's Field II (USA)").
SRC_SIZE = 571766496
SRC_CRC32 = 0xF8A4C585

# --- BOB: head-bob disable (FUN_8002ed60): `sh v0,0x2650` -> `sh zero,0x2650`. ---
BOB_SIG = bytes.fromhex(
    "23106200""1b80013c""502622a4""bdbc0008""00000000""1b80013c""502620a4")
BOB_OFF = 0x0a          # rt byte of `sh v0,0x2650`: 0x22 (v0) -> 0x20 (zero)

# --- CAP: framerate cap (FUN_80019614): two `sltiu v0,v0,0x4`, imm 4 -> N. ---
CAP_SIG = bytes.fromhex(
    "0400422c""09004010""00000000""21806000""43e4010c""21200000"
    "0000028e""00000000""0400422c""faff4014")
CAP_OFF = (0, 0x20)
CAP_NEW = {"half": 0x02, "quarter": 0x01}

# --- WALK: player move (FUN_8002e3f8): two `sra rd,v0,0xc` funct byte 0x03 -> N. ---
WALK_SIG = bytes.fromhex(
    "31db010c""03a30200""2800a88f""00000000""18004800""21b00000"
    "6000a0af""5800a0af""5000a0af""4800a0af""4000a0af""3000b4af"
    "12100000""03930200")
WALK_OFF = (4, 0x34)
WALK_NEW = {"half": 0x43, "quarter": 0x83}

# --- TURN: turn-max base (FUN_80030fcc): `ori v0,zero,0x20` / `,0x28`. ---
TURN_SIG = bytes.fromhex(
    "c8000234""1b80013c""642622ac""20000234""1b80013c""682622ac"
    "00000296""25186400""24104300""03004014""28000234")
TURN_OFF20 = 0x0c
TURN_OFF28 = 0x28
TURN_NEW20 = {"half": 0x10, "quarter": 0x08}
TURN_NEW28 = {"half": 0x14, "quarter": 0x0a}

# --- ENEMY movement (code cave). All enemy movement funnels through FUN_8004dbc8,
# which loads per-frame velocity (vx=s3, vz=s0) then does enemy.pos += vx/vz. No free
# inline slot, so redirect `move s7,s3` (@0x8004dc38) to a cave that round-half-away
# /N's the velocity (so slow/diagonal enemies don't lose small velocities to
# truncation), redoes the two moves, and jumps back to the loop @0x8004dc40. ---
ENEMY_JSIG = bytes.fromhex("00001385""04001085""21b86002""21b00002")  # @0x8004dc30
ENEMY_JSIG_VADDR = 0x8004dc30
ENEMY_MOVE_OFF = 8               # the `move s7,s3` (21b86002) -> j cave
ENEMY_JMP = 0x0801fbe0           # j 0x8007EF80
CAVE_VADDR = 0x8007EF80          # inter-function code-padding cave (file-verified free)
ENEMY_CAVE = {
    "quarter": [0x00134FC3, 0x00094880, 0x25290002, 0x02699821, 0x00139883,
                0x00104FC3, 0x00094880, 0x25290002, 0x02098021, 0x00108083,
                0x0260b821, 0x0200b021, 0x08013710, 0x00000000],
    "half":    [0x00134FC3, 0x00094840, 0x25290001, 0x02699821, 0x00139843,
                0x00104FC3, 0x00094840, 0x25290001, 0x02098021, 0x00108043,
                0x0260b821, 0x0200b021, 0x08013710, 0x00000000],
}

# --- ATTACK-BAR (weapon charge 0x2502) recharge /N. The recharge sits behind a gate
# `bne v0,zero,...` @0x8002de00 where v0 = (0x265c & 0x1870). Redirect `lhu v1,0x1870(v1)`
# (@0x8002ddf4, delay slot is a nop) to a cave that ORs (frameclock & (N-1)) into the gate
# so the whole recharge runs only every Nth frame. ---
ATTACK_SIG = bytes.fromhex(
    "1b80023c""5c264294""0880033c""70186394""00000000""24104300"
    "2d004014""00000000""1b80023c""f3244290")
ATTACK_PATCH_OFF = 0x0c
ATTACK_JMP = 0x0801fbf0          # j 0x8007EFC0
ATK_CAVE_VADDR = 0x8007EFC0
ATTACK_CAVE = {
    "quarter": [0x94631870, 0x3C01801B, 0x94212580, 0x00431024,
                0x30210003, 0x00411025, 0x0800B780, 0x00000000],
    "half":    [0x94631870, 0x3C01801B, 0x94212580, 0x00431024,
                0x30210001, 0x00411025, 0x0800B780, 0x00000000],
}

# --- MAGIC-STAMINA gauge (0x2506, full=5000 to cast) fill /N. Filled by
# `0x2506 += sVar3` (addu v1,v1,v0 @0x80030220). The game clock reads unreliably here,
# so the cave uses its OWN counter byte (@0x800810B0) and gates the add every Nth call. ---
MAGIC_SIG = bytes.fromhex(
    "06256394""00000000""21186200""1b80013c""062523a4")
MAGIC_PATCH_OFF = 0x08
MAGIC_JMP = 0x0802041e           # j 0x80081078
MAG_CAVE_VADDR = 0x80081078      # 300-byte gap; self-counter byte @0x800810B0
MAGIC_CAVE = {
    "quarter": [0x3C018008, 0x802410B0, 0x00000000, 0x24840001, 0xA02410B0, 0x30840003,
                0x14800002, 0x00000000, 0x00621821, 0x0800C089, 0x00000000],
    "half":    [0x3C018008, 0x802410B0, 0x00000000, 0x24840001, 0xA02410B0, 0x30840001,
                0x14800002, 0x00000000, 0x00621821, 0x0800C089, 0x00000000],
}

# --- MAGIC recharge DELAY: the magic delay timer 0x24f4 decrements ungated, so the magic
# bar starts refilling 4x too soon. xN its set value `ori v0,zero,0x3c`(=60) @0x80030120
# so it lasts as long as the (gated) attack delay. ---
MAGDELAY_SIG = bytes.fromhex("3c000234""1b80013c""f42422a0")
MAGDELAY_OFF = 0
MAGDELAY_NEW = {"quarter": 0xf0, "half": 0x78}

TEXT_VADDR = 0x80011000


def _file_off(v):
    return (v - TEXT_VADDR) + 0x800            # GAME.EXE vaddr -> file offset


def _bin_off(f):
    return f + (f // 2048) * 304               # MODE2/2352 file offset -> raw .bin offset


def find_once(data, sig, name):
    i = data.find(sig)
    if i < 0:
        raise SystemExit("ERROR: %s signature not found "
                         "(is this the right King's Field II (USA) dump?)" % name)
    if data.find(sig, i + 1) >= 0:
        raise SystemExit("ERROR: %s signature not unique" % name)
    return i


def apply_patches(data, mode):
    """Apply all 60 fps patches to `data` (a bytearray) in place. Returns nothing."""
    c = find_once(data, CAP_SIG, "cap")
    for off in CAP_OFF:
        assert data[c + off] == 0x04, "cap byte mismatch"
        data[c + off] = CAP_NEW[mode]
    print("CAP        @0x%X,0x%X  cap 4->%d" % (c + CAP_OFF[0], c + CAP_OFF[1], CAP_NEW[mode]))

    b = find_once(data, BOB_SIG, "bob")
    assert data[b + BOB_OFF] == 0x22, "bob byte mismatch"
    data[b + BOB_OFF] = 0x20
    print("BOB        @0x%X  disabled" % (b + BOB_OFF))

    w = find_once(data, WALK_SIG, "walk")
    for off in WALK_OFF:
        assert data[w + off] == 0x03, "walk byte mismatch"
        data[w + off] = WALK_NEW[mode]
    print("WALK       @0x%X,0x%X  sra ->0x%02x" % (
        w + WALK_OFF[0], w + WALK_OFF[1], WALK_NEW[mode]))

    t = find_once(data, TURN_SIG, "turn")
    assert data[t + TURN_OFF20] == 0x20 and data[t + TURN_OFF28] == 0x28, "turn byte mismatch"
    data[t + TURN_OFF20] = TURN_NEW20[mode]
    data[t + TURN_OFF28] = TURN_NEW28[mode]
    print("TURN       @0x%X,0x%X" % (t + TURN_OFF20, t + TURN_OFF28))

    # GAME.EXE byte-0 in the raw .bin (anchor for cave offset math).
    je = find_once(data, ENEMY_JSIG, "enemy")
    assert data[je + ENEMY_MOVE_OFF:je + ENEMY_MOVE_OFF + 4] == bytes.fromhex("21b86002"), \
        "enemy move byte mismatch"
    base = je - _bin_off(_file_off(ENEMY_JSIG_VADDR))
    assert data[base:base + 8] == b"PS-X EXE", "GAME.EXE anchor mismatch (0x%X)" % base

    def inject(name, sig, patch_off, old_hex, jmp, cave_vaddr, cave_words):
        idx = find_once(data, sig, name)
        assert data[idx + patch_off:idx + patch_off + 4] == bytes.fromhex(old_hex), \
            "%s patch byte mismatch" % name
        cbin = base + _bin_off(_file_off(cave_vaddr))
        assert all(x == 0 for x in data[cbin:cbin + 4 * len(cave_words)]), \
            "%s cave region not free" % name
        data[idx + patch_off:idx + patch_off + 4] = jmp.to_bytes(4, "little")
        for k, word in enumerate(cave_words):
            data[cbin + 4 * k:cbin + 4 * k + 4] = word.to_bytes(4, "little")
        print("%-10s @0x%X -> cave @bin0x%X (vaddr 0x%X)" % (name.upper(), idx + patch_off,
                                                             cbin, cave_vaddr))

    inject("enemy", ENEMY_JSIG, ENEMY_MOVE_OFF, "21b86002", ENEMY_JMP, CAVE_VADDR,
           ENEMY_CAVE[mode])
    inject("attack", ATTACK_SIG, ATTACK_PATCH_OFF, "70186394", ATTACK_JMP, ATK_CAVE_VADDR,
           ATTACK_CAVE[mode])
    inject("magic", MAGIC_SIG, MAGIC_PATCH_OFF, "21186200", MAGIC_JMP, MAG_CAVE_VADDR,
           MAGIC_CAVE[mode])

    md = find_once(data, MAGDELAY_SIG, "magdelay")
    assert data[md + MAGDELAY_OFF] == 0x3c, "magdelay byte mismatch"
    data[md + MAGDELAY_OFF] = MAGDELAY_NEW[mode]
    print("MAGIC-DELAY @0x%X  60->%d frames" % (md + MAGDELAY_OFF, MAGDELAY_NEW[mode]))


def make_bps(source, target):
    """Build a BPS patch (the changed bytes only -- no game code) from source->target.

    Both must be the same length (all patches are same-size). The patch stores SourceRead
    runs (offsets/lengths, not data) for unchanged spans and TargetRead runs (our edited
    bytes) for changed spans, plus source/target/patch CRC32 footers."""
    assert len(source) == len(target), "BPS: source/target size differ"

    def varint(n):
        out = bytearray()
        while True:
            x = n & 0x7f
            n >>= 7
            if n == 0:
                out.append(0x80 | x)
                return out
            out.append(x)
            n -= 1

    out = bytearray(b"BPS1")
    out += varint(len(source))
    out += varint(len(target))
    out += varint(0)                       # no metadata
    i, n = 0, len(target)
    while i < n:
        same = source[i] == target[i]
        j = i + 1
        while j < n and (source[j] == target[j]) == same:
            j += 1
        length = j - i
        out += varint(((length - 1) << 2) | (0 if same else 1))  # 0=SourceRead 1=TargetRead
        if not same:
            out += target[i:j]
        i = j
    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="King's Field II (USA) 60 fps patcher")
    ap.add_argument("input", help="path to your King's Field II (USA) .bin (MODE2/2352)")
    ap.add_argument("output", help="path to write the patched .bin")
    ap.add_argument("--mode", choices=("quarter", "half"), default="quarter",
                    help="quarter = 60 fps + 1/4 speed (default); half = 30 fps + 1/2 speed")
    ap.add_argument("--bps", metavar="patch.bps",
                    help="also write a shareable BPS patch (contains only our edits)")
    ap.add_argument("--no-crc-check", action="store_true",
                    help="skip the source size/CRC verification")
    args = ap.parse_args(argv)

    source = bytearray(open(args.input, "rb").read())

    if not args.no_crc_check:
        crc = zlib.crc32(source) & 0xffffffff
        if len(source) != SRC_SIZE or crc != SRC_CRC32:
            print("WARNING: input does not match the known King's Field II (USA) dump")
            print("  expected size=%d crc32=0x%08X" % (SRC_SIZE, SRC_CRC32))
            print("  got      size=%d crc32=0x%08X" % (len(source), crc))
            print("  (continuing; patches are signature-located. Use --no-crc-check to silence.)")

    data = bytearray(source)
    apply_patches(data, args.mode)
    open(args.output, "wb").write(data)
    print("wrote %s (%d bytes), mode=%s" % (args.output, len(data), args.mode))

    if args.bps:
        bps = make_bps(bytes(source), bytes(data))
        open(args.bps, "wb").write(bps)
        print("wrote %s (%d bytes BPS patch -- shareable, no game code)" % (args.bps, len(bps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
