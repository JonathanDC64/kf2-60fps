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

# --- PLAYER SWING animation (FUN_8002d2a0). A normal melee swing advances the arc
# `DAT_801b25a4 += s2` per frame (s2 = uVar2 = weapon swing-speed, loaded from
# weapon[0x1c]/[0x24]); the arc runs 0..0xfff then ends. At 60fps it completes 4x too fast.
# We redirect `lhu v0,0x0(s0)` (@0x8002d814; its delay slot `lui v1,0x801b` is safe) to a
# cave that re-loads the arc and /N's s2 -- scaling the advance AND the hit-detection
# windows together (both use s2), so the swing is /N slower and hits still register. ---
# @0x8002d80c: lui s0 / addiu s0,0x25a4 / lhu v0,0(s0) / lui v1 / lbu v1,0x25ae(v1)
SWING_SIG = bytes.fromhex(
    "1b80103c""a4251026""00000296""1b80033c""ae256390")
SWING_PATCH_OFF = 0x08          # the `lhu v0,0x0(s0)` (00000296) -> j cave
SWING_JMP = 0x08020430          # j 0x800810C0
SWING_CAVE_VADDR = 0x800810C0   # in the same 300-byte gap, past the magic cave + its counter
#   cave: lhu v0,0x0(s0) / sra s2,s2,(log2 N) / j 0x8002d81c / nop
SWING_CAVE = {
    "quarter": [0x96020000, 0x00129083, 0x0800B606, 0x00000000],   # sra s2,s2,2
    "half":    [0x96020000, 0x00129043, 0x0800B606, 0x00000000],   # sra s2,s2,1
}

# --- ENEMY TURNING / facing slew (FUN_8004e928) -- the universal "rotate toward a target
# angle" routine every turning AI state funnels through. An angular velocity obj[0x58] ramps
# by +/-accel each frame (clamped to +/-maxrate), then the facing yaw advances
# `obj[0x42] += obj[0x58]` (with snap-to-target on overshoot). At 60fps every enemy turns 4x
# fast. Redirect the velocity load to a cave that advances by velocity/N instead -- using the
# already-loaded SIGNED copy (v1) so negative turn rates shift correctly. The accel ramp and
# the snap-to-target are untouched, so enemies still end up facing the player, just turning
# N x slower. One injection covers every enemy + NPC at all distances. ---
# @0x8004e9d8: lh a1,0x42(s0) / lhu v0,0x58(s0) / lh v1,0x58(s0) / addu v0,v0,a1 / blez v1 / sh v0,0x42
TURNFACE_SIG = bytes.fromhex(
    "42000586""58000296""58000386""21104500""0b006018""420002a6")
TURNFACE_PATCH_OFF = 0x04          # the `lhu v0,0x58(s0)` (58000296) -> j cave
TURNFACE_JMP = 0x08020438          # j 0x800810E0
TURNFACE_CAVE_VADDR = 0x800810E0   # same 300-byte gap, past the magic+swing caves
#   cave: nop (load-delay for v1) / sra v0,v1,(log2 N) / addu v0,v0,a1 / j 0x8004e9e8 / nop
TURNFACE_CAVE = {
    "quarter": [0x00000000, 0x00031083, 0x00451021, 0x08013A7A, 0x00000000],  # sra v0,v1,2
    "half":    [0x00000000, 0x00031043, 0x00451021, 0x08013A7A, 0x00000000],  # sra v0,v1,1
}

# --- ENEMY/NPC animation (FUN_8004db3c) -- the shared per-object animation-phase advance:
# `obj[0x18] += step` (clamped [0,0xfff]; step = data[0x8], stored sign at obj+0x66), called
# per-frame for every object in the update loop FUN_800500a8. At 60fps all enemy + NPC
# animations (walk/idle/attack) run 4x fast. The advance is `addu v0,v1,v0` @0x8004db60 with
# a load-delay `nop` right before it @0x8004db5c -- replace that nop with `sra v1,v1,N` to /N
# the step. Hit triggers use FIXED phase thresholds (not the step), so they stay correct. ---
# @0x8004db58: lhu v0,0x18(a0) / nop / addu v0,v1,v0 / sh v0,0x18(a0) / sll v0,v0,0x10
ENEMYANIM_SIG = bytes.fromhex(
    "18008294""00000000""21106200""180082a4""00140200")
ENEMYANIM_OFF = 0x04             # the load-delay nop -> sra v1,v1,N
ENEMYANIM_NEW = {"quarter": 0x00031883, "half": 0x00031843}   # sra v1,v1,2 / sra v1,v1,1

# --- DISTANT (LOD) enemy animation (FUN_8004db08) -- a sibling of FUN_8004db3c used for
# obj[6]==2 (far/simplified) enemies: `obj[0x18] = (obj[0x18] + step) & 0xfff`. Same shape,
# same fix: the load-delay nop @0x8004db28 (before `addu v0,v1,v0`) -> sra v1,v1,N. ---
# @0x8004db24: lhu v0,0x18(a0) / nop / addu v0,v1,v0 / andi v0,v0,0xfff / jr ra
ENEMYANIM_FAR_SIG = bytes.fromhex(
    "18008294""00000000""21106200""ff0f4230""0800e003")
ENEMYANIM_FAR_OFF = 0x04
ENEMYANIM_FAR_NEW = {"quarter": 0x00031883, "half": 0x00031843}

# --- MAGIC recharge DELAY: the magic delay timer 0x24f4 decrements ungated, so the magic
# bar starts refilling 4x too soon. xN its set value `ori v0,zero,0x3c`(=60) @0x80030120
# so it lasts as long as the (gated) attack delay. ---
MAGDELAY_SIG = bytes.fromhex("3c000234""1b80013c""f42422a0")
MAGDELAY_OFF = 0
MAGDELAY_NEW = {"quarter": 0xf0, "half": 0x78}

# --- DOORS (FUN_80047010, the interactive-world-object state machine) -- a per-frame state
# counter obj[0x38] drives open/hold/close phases; the swing angle obj[0x1e] ramps +/-0x20
# per frame to 0x400 (90deg). Open lasts until the counter hits a trigger value (then it jumps
# to the hold phase); close runs over a counter window. At 60fps the door snaps open/closed 4x
# fast. Fix = ÷N the open+close ramp steps AND lengthen the open trigger / close window N x, so
# the door travels the full 90deg over N x the frames. The player-push sub-phase (counter<0x15)
# is left untouched (so the player isn't shoved N x as far). All same-size byte edits. ---
# Open ramp + open-end trigger: lhu v0,0x1e(s2)/ori v1,0x81/sb/addiu v0,v0,0x20/sh/.../ori v0,0x1f
DOOR_OPEN_SIG = bytes.fromhex(
    "1e004296""81000334""f9ff43a2""20004224""1e0042a6""18000234""10002216""1f000234")
DOOR_OPEN_RAMP_OFF = 0x0c       # addiu v0,v0,0x20  (open step) -> 0x08/0x10
DOOR_OPEN_TRIG_OFF = 0x1c       # ori v0,zero,0x1f  (open ends at counter==trigger) -> 0x7f/0x3f
DOOR_OPEN_RAMP = {"quarter": 0x08, "half": 0x10}
DOOR_OPEN_TRIG = {"quarter": 0x7f, "half": 0x3f}
# Open-block window guard: ... sra s1,v0,0x10 / slti v0,s1,0x20
DOOR_OPENWIN_SIG = bytes.fromhex(
    "38004296""00000000""01004324""00140200""038c0200""2000222a")
DOOR_OPENWIN_OFF = 0x14         # slti v0,s1,0x20 -> 0x80/0x40 (keep window > trigger)
DOOR_OPENWIN = {"quarter": 0x80, "half": 0x40}
# Close window end: slti v0,s1,0x12c / bne / slti v0,s1,0x14c
DOOR_CLOSEWIN_SIG = bytes.fromhex("2c01222a""5b0c4014""4c01222a")
DOOR_CLOSEWIN_OFF = 0x08        # slti v0,s1,0x14c (low byte) -> 0xac(0x1ac)/0x6c(0x16c)
DOOR_CLOSEWIN = {"quarter": 0xac, "half": 0x6c}
# Close ramp: lhu v0,0x1e(s2) / nop / addiu v0,v0,-0x20 / j 0x8004b4d0
DOOR_CLOSERAMP_SIG = bytes.fromhex("1e004296""00000000""e0ff4224""342d0108")
DOOR_CLOSERAMP_OFF = 0x08       # addiu v0,v0,-0x20 (low byte) -> 0xf8(-0x08)/0xf0(-0x10)
DOOR_CLOSERAMP = {"quarter": 0xf8, "half": 0xf0}

# --- MENU input-repeat speed (FUN_800279d8) -- the menus run their own blocking, vblank-driven
# loop. After a button is read, this routine waits for release but bails after 8 vblanks
# (`slti v0,v0,0x8`); if you're still holding, the menu re-processes the input = auto-repeat
# every ~8 vblanks. At 60fps that's ~4x too fast (cursor scrolls/zooms). Bump the 8 -> 0x20
# (32 vblanks) for ÷4 (single taps stay instant; only held navigation slows). ---
# @0x80027a00: andi v0,v0,0xffff / beq / move v0,s0 / slti v0,v0,0x8 / beq / addiu s0,s0,1 /
#              jal 0x8007910c (VSync) -- the per-iteration wait of the release/repeat loop.
# Two edits: (1) the repeat count 0x8 -> 0x20 (÷4), and (2) like the menu-cap, redirect the
# loop's VSync to FUN_80019614 so each iteration blocks one real vblank (raw VSync(0) doesn't
# block under overclock, which made the repeat collapse to "too fast" in DuckStation).
MENU_SIG = bytes.fromhex(
    "ffff4230""09004010""21100002""08004228""05004010""01001026""43e4010c")
MENU_OFF = 0x0c                 # slti v0,v0,0x8 (repeat count, in FUN_80019614-vblank units)
# The menu is vblank-paced (60fps) in BOTH original and patched, so the repeat count needn't be
# scaled -- 8 was always correct (~12fps during hold, matching unpatched). The real fix is the
# deterministic vblank wait below (MENU_VSYNC). Quarter keeps 8 (FUN_80019614 = 1 vblank each);
# half uses 4 since FUN_80019614 waits 2 vblanks in half mode (4*2 = 8 vblanks, same feel).
MENU_NEW = {"quarter": 0x08, "half": 0x04}
MENU_VSYNC_OFF = 0x18           # jal 0x8007910c (VSync) -> jal 0x80019614 (deterministic vblank)
MENU_VSYNC_OLD = 0x0c01e443
MENU_VSYNC_NEW = 0x0c006585

# --- MENU fps cap (FUN_800270f8) -- the menus' own loop presents every iteration and only calls
# `VSync(0)` once, which doesn't block (the BIOS VSync(0) just yields; the real frame gate is the
# game's vblank counter `DAT_801c12ec`). So with a high CPU overclock the menu spins way past 60fps
# (~270). The overworld cap `FUN_80019614` blocks on that counter (`while(ctr<N) VSync(0); ctr=0`)
# and honors our CAP patch. Fix: redirect the menu's `jal VSync` to `jal FUN_80019614`, so each
# menu present waits one vblank like the overworld. Same-size word edit (mode-independent; the
# vblank count N comes from the already-patched CAP). ---
# @0x800270f8: addiu sp,-0x18 / clear a0 / sw ra / jal 0x80079ba0 / sw s0 /
#              jal 0x8007910c (VSync) / clear a0 / lui s0,0x801b / addiu s0,-0x1518
MENUCAP_SIG = bytes.fromhex(
    "e8ffbd27""21200000""1400bfaf""e8e6010c""1000b0af"
    "43e4010c""21200000""1b80103c""e8ea1026")
MENUCAP_OFF = 0x14              # jal 0x8007910c (VSync) -> jal 0x80019614 (FUN_80019614)
MENUCAP_OLD = 0x0c01e443        # jal 0x8007910c
MENUCAP_NEW = 0x0c006585        # jal 0x80019614
MENUCAP_VADDR = 0x800270f8      # the MENU flush (3 byte-identical copies exist; cap ONLY this one --
#                                 0x80035700 is the overworld present, already capped by the main loop)

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
    inject("swing", SWING_SIG, SWING_PATCH_OFF, "00000296", SWING_JMP, SWING_CAVE_VADDR,
           SWING_CAVE[mode])
    inject("turnface", TURNFACE_SIG, TURNFACE_PATCH_OFF, "58000296", TURNFACE_JMP,
           TURNFACE_CAVE_VADDR, TURNFACE_CAVE[mode])

    ea = find_once(data, ENEMYANIM_SIG, "enemyanim")
    assert data[ea + ENEMYANIM_OFF:ea + ENEMYANIM_OFF + 4] == bytes(4), "enemyanim byte mismatch"
    data[ea + ENEMYANIM_OFF:ea + ENEMYANIM_OFF + 4] = ENEMYANIM_NEW[mode].to_bytes(4, "little")
    print("ENEMY-ANIM @0x%X  nop -> sra v1,v1,%d" % (
        ea + ENEMYANIM_OFF, 2 if mode == "quarter" else 1))

    ef = find_once(data, ENEMYANIM_FAR_SIG, "enemyanim_far")
    assert data[ef + ENEMYANIM_FAR_OFF:ef + ENEMYANIM_FAR_OFF + 4] == bytes(4), \
        "enemyanim_far byte mismatch"
    data[ef + ENEMYANIM_FAR_OFF:ef + ENEMYANIM_FAR_OFF + 4] = \
        ENEMYANIM_FAR_NEW[mode].to_bytes(4, "little")
    print("ENEMY-ANIM-FAR @0x%X  nop -> sra v1,v1,%d" % (
        ef + ENEMYANIM_FAR_OFF, 2 if mode == "quarter" else 1))

    md = find_once(data, MAGDELAY_SIG, "magdelay")
    assert data[md + MAGDELAY_OFF] == 0x3c, "magdelay byte mismatch"
    data[md + MAGDELAY_OFF] = MAGDELAY_NEW[mode]
    print("MAGIC-DELAY @0x%X  60->%d frames" % (md + MAGDELAY_OFF, MAGDELAY_NEW[mode]))

    # --- DOORS: ÷N the open/close ramps + lengthen the open trigger / close window N x ---
    do = find_once(data, DOOR_OPEN_SIG, "door_open")
    assert data[do + DOOR_OPEN_RAMP_OFF] == 0x20 and data[do + DOOR_OPEN_TRIG_OFF] == 0x1f, \
        "door_open byte mismatch"
    data[do + DOOR_OPEN_RAMP_OFF] = DOOR_OPEN_RAMP[mode]
    data[do + DOOR_OPEN_TRIG_OFF] = DOOR_OPEN_TRIG[mode]
    dw = find_once(data, DOOR_OPENWIN_SIG, "door_openwin")
    assert data[dw + DOOR_OPENWIN_OFF] == 0x20, "door_openwin byte mismatch"
    data[dw + DOOR_OPENWIN_OFF] = DOOR_OPENWIN[mode]
    dc = find_once(data, DOOR_CLOSEWIN_SIG, "door_closewin")
    assert data[dc + DOOR_CLOSEWIN_OFF] == 0x4c, "door_closewin byte mismatch"
    data[dc + DOOR_CLOSEWIN_OFF] = DOOR_CLOSEWIN[mode]
    dr = find_once(data, DOOR_CLOSERAMP_SIG, "door_closeramp")
    assert data[dr + DOOR_CLOSERAMP_OFF] == 0xe0, "door_closeramp byte mismatch"
    data[dr + DOOR_CLOSERAMP_OFF] = DOOR_CLOSERAMP[mode]
    print("DOOR open ramp@0x%X trig@0x%X win@0x%X / close win@0x%X ramp@0x%X" % (
        do + DOOR_OPEN_RAMP_OFF, do + DOOR_OPEN_TRIG_OFF, dw + DOOR_OPENWIN_OFF,
        dc + DOOR_CLOSEWIN_OFF, dr + DOOR_CLOSERAMP_OFF))

    mn = find_once(data, MENU_SIG, "menu")
    assert data[mn + MENU_OFF] == 0x08, "menu byte mismatch"
    assert int.from_bytes(data[mn + MENU_VSYNC_OFF:mn + MENU_VSYNC_OFF + 4], "little") == \
        MENU_VSYNC_OLD, "menu vsync byte mismatch"
    data[mn + MENU_OFF] = MENU_NEW[mode]
    data[mn + MENU_VSYNC_OFF:mn + MENU_VSYNC_OFF + 4] = MENU_VSYNC_NEW.to_bytes(4, "little")
    print("MENU repeat @0x%X  8->%d vblanks (+ deterministic vblank wait)" % (
        mn + MENU_OFF, MENU_NEW[mode]))

    # There are 3 byte-identical copies of this flush function. ONLY the menu one
    # (vaddr 0x800270f8) must be capped -- the others are the overworld present (0x80035700,
    # called by FUN_800422b8 and already capped by the main loop) and 0x80061894; capping those
    # would add a 2nd vblank wait and halve their fps. So target the menu copy by address.
    mc = base + _bin_off(_file_off(MENUCAP_VADDR))
    assert data[mc:mc + len(MENUCAP_SIG)] == MENUCAP_SIG, "menucap: flush not at 0x800270f8"
    assert int.from_bytes(data[mc + MENUCAP_OFF:mc + MENUCAP_OFF + 4], "little") == MENUCAP_OLD, \
        "menucap byte mismatch"
    data[mc + MENUCAP_OFF:mc + MENUCAP_OFF + 4] = MENUCAP_NEW.to_bytes(4, "little")
    print("MENU-CAP @0x%X (menu flush 0x800270f8 only; overworld flush untouched)" % (mc + MENUCAP_OFF))


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
