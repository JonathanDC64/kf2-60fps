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
import hashlib
import math
import sys
import zlib

# Patcher version (single source of truth -- exported to the manifest, shown on the CLI + web UI).
# See CHANGELOG.md. Bump on every user-visible change.
VERSION = "1.4.0"

# Reference fingerprint of the known-good source (Redump "King's Field II (USA)", SLUS-00255).
SRC_SERIAL = "SLUS-00255"
SRC_SIZE = 571766496
SRC_CRC32 = 0xF8A4C585
SRC_MD5 = "bf503b25c229ae048127a16679396d17"
SRC_SHA1 = "131d2574f6ea101823193845f001bb58cdd3ed5e"

# --- BOB: head-bob (FUN_8002ed60 @LAB_8002f270). When walking, a phase DAT_801b2652 advances by the
# walk-step rate DAT_801b264a each frame and the camera bob = f(rsin(phase)). At 60fps the phase
# advances 4x too fast -> the bob oscillates 4x too fast. Two ways to handle it:
#   * FIX (default): scale the phase increment /N so the bob runs at the original frequency (amplitude
#     unchanged). The add `phase += incr` sits behind a load-delay nop (`lhu v0,0x264a; nop; addu`),
#     so we can't just shift v0 in the nop slot (R3000 load delay). Instead we REORDER the two load
#     pairs (load the increment first) which frees that slot for `sra v0,v0,N` with no hazard:
#       lui v0/lhu v0,0x264a/lui a0/lhu a0,0x2652/sra v0,v0,N/addu a0,a0,v0
#   * OFF (--bob off): the original disable -- store 0 to the bob output `sh v0,0x2650` -> `sh zero`.
BOBFIX_SIG = bytes.fromhex("1b80043c" "52268494" "1b80023c" "4a264294" "00000000" "21208200")
# old: lui a0 / lhu a0,0x2652(a0) / lui v0 / lhu v0,0x264a(v0) / nop / addu a0,a0,v0
BOBFIX_NEW = {  # reordered + sra v0,v0,N (N=2 quarter, 1 half): lui v0/lhu v0/lui a0/lhu a0/sra/addu
    "quarter": bytes.fromhex("1b80023c" "4a264294" "1b80043c" "52268494" "83100200" "21208200"),
    "half":    bytes.fromhex("1b80023c" "4a264294" "1b80043c" "52268494" "43100200" "21208200"),
}
BOB_SIG = bytes.fromhex(
    "23106200""1b80013c""502622a4""bdbc0008""00000000""1b80013c""502620a4")
BOB_OFF = 0x0a          # rt byte of `sh v0,0x2650`: 0x22 (v0) -> 0x20 (zero) -- the --bob off disable

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

# --- LOOK: vertical camera / pitch (FUN_8002f5c0). Pitch angle DAT_801b2610 advances by the pitch
# velocity DAT_801b264e each frame. Unlike yaw (which rides the TURN step DAT_801b2668), pitch uses a
# hardcoded velocity (ramp +-3, clamp +-0x20) the TURN patch never touched -> at 60fps the vertical
# look is ~4x too fast. At each of the two apply sites the velocity is copied `addu v1,v0,zero` right
# before `pitch += v1`; we change that copy to an arithmetic `sra v1,v0,N` (N=2 quarter, 1 half) so
# the pitch advances 1/4 (1/2) per frame -- correct max look speed, the ramp/clamp feel preserved.
# Two sites in the same function: looking up (blez-guarded @0x8002f92c) and down (bgez @0x8002f974).
LOOK_UP_SIG = bytes.fromhex("4e264284" "00000000" "10004018" "21184000")  # lh v0,0x264e/nop/blez v0/addu v1,v0,zero
LOOK_DN_SIG = bytes.fromhex("4e264284" "00000000" "0e004104" "21184000")  # lh v0,0x264e/nop/bgez v0/addu v1,v0,zero
LOOK_OFF = 0x0c                    # the `addu v1,v0,zero` (00401821) word -> `sra v1,v0,N`
LOOK_OLD = 0x00401821              # addu v1,v0,zero
LOOK_NEW = {"quarter": 0x00021883, "half": 0x00021843}   # sra v1,v0,2 / sra v1,v0,1

# --- POISON: poison / damage-over-time tick (handler @0x80031e9c). HP -1 fires when the poison
# countdown DAT_801b255c satisfies `(a0 % 30) == 0` (computed by a magic-divide: `mult a0,0x88888889
# / mfhi / addu / sra v1,v1,4` = a0/30, then `*30` reconstruct and `a0 - that`). At 60fps the counter
# advances 4x faster -> poison ticks ~4x too often (verified live: -1 HP every ~120 frames). We widen
# the modulus 30 -> 120 (quarter) / 60 (half) with two single-shift edits: the divide `sra v1,v1,4`
# -> `,6`/`,5` (a0/30 -> a0/120 / a0/60) and the reconstruct `sll v0,v0,1` -> `,3`/`,2` (*30 -> *120 /
# *60). Result: tick fires only at multiples of 120/60 (exact, no bursts) -> poison ticks /4 (/2).
POISON_SIG = bytes.fromhex("8888023c" "89884234" "18008200" "c3170500" "10180000" "21186400"
                           "03190300" "23186200" "00110300" "23104300" "40100200" "23108200")
POISON_DIV_OFF = 0x18              # `sra v1,v1,4` (0x00031903) -- divide shift
POISON_DIV_OLD = 0x00031903
POISON_DIV_NEW = {"quarter": 0x00031983, "half": 0x00031943}   # sra v1,v1,6 (/120) / sra v1,v1,5 (/60)
POISON_MUL_OFF = 0x28              # `sll v0,v0,1` (0x00021040) -- reconstruct multiply
POISON_MUL_OLD = 0x00021040
POISON_MUL_NEW = {"quarter": 0x000210c0, "half": 0x00021080}   # sll v0,v0,3 (*120) / sll v0,v0,2 (*60)

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

# --- GRAVITY / falling physics (FUN_8002ee.. , player vertical update) ---
# Free-fall integrates N^2: each frame does `Y += velocity; velocity += 0x28` (accel = 40/frame,
# velocity halfword @0x801b2656). The landing path derives FALL DAMAGE from velocity^2 (gated at
# velocity >= 0x1e0) and clamps terminal velocity (0x200). A flat divide would desync those.
# Trick: KEEP the velocity *value* identical to the original (so damage + clamps stay correct for
# free) by dividing the accel, and divide ONLY the position step. Real-world fall rate is preserved
# when  F^2 * accel' / 2^k == F0^2 * accel  -> accel'/2^k = 2.5. Quarter: accel'=0x0a, k=2 (>>2);
# velocity = 60t*10 = 600t = original 15t*40, so 0x1e0/0x200/damage all fire at the same instant.
# Half: accel'=0x14, k=1 (>>1).
# @0x8002eed0..ef1c.  Redirect the velocity load `lh v1,0x2656(v1)` (@0x8002eedc) to a cave that
# reloads + arithmetic-shifts it before `addu s0,v1,v0` (the proposed-Y add), and divide the accel.
GRAV_SIG = bytes.fromhex(
    "0000448e""0800468e""1b80033c""56266384""20030734""1000b3af""0400428e""1400b4af"
    "21806200""cecf000c""21280002""21884000""0e002016""00000000""1b80023c""56264294"
    "040050ae""120042a6""28004224""1b80013c")
GRAV_REDIR_OFF = 0x0c              # `lh v1,0x2656(v1)` (56266384) -> j cave
GRAV_REDIR_OLD = "56266384"
GRAV_INC_OFF = 0x48                # `addiu v0,v0,0x28` accel immediate (low byte) -> 0x0a / 0x14
GRAV_INC_NEW = {"quarter": 0x0a, "half": 0x14}
GRAV_JMP = 0x08020440              # j 0x80081100
GRAV_CAVE_VADDR = 0x80081100       # same 300-byte gap, past magic+swing+turnface caves
#   cave: lui v1,0x801b / lh v1,0x2656(v1) / nop (R3000 LOAD DELAY) / sra v1,v1,(log2 N)
#         / j 0x8002eee4 / nop.  The nop after lh is REQUIRED: on the R3000 the loaded value is
#         not available to the next instruction, so sra would shift the stale v1 without it.
GRAV_CAVE = {
    "quarter": [0x3c03801b, 0x84632656, 0x00000000, 0x00031883, 0x0800bbb9, 0x00000000],  # sra,2
    "half":    [0x3c03801b, 0x84632656, 0x00000000, 0x00031843, 0x0800bbb9, 0x00000000],  # sra,1
}

# --- ANIMATED BILLBOARDS / fire (FUN_80040ae4, the 200-object sprite renderer) ---
# Each animated sprite advances its texture frame only when `global_clock % period == 0` (clock
# @0x80182964 bumped +1/frame, per-sprite `period` = lbu -1(s0)). The fire (and other flames) use
# period=1 -> advance EVERY frame, so at 60fps they cycle 4x too fast. Scaling the clock is a no-op
# for period=1 (anything % 1 == 0), so instead multiply the PERIOD by N: `clock % (period*N) == 0`
# advances every N*period frames -- correct for ALL periods incl. 1. Redirect the clock load
# `lw v0,0x2964(v0)` (@0x80041a08) to a cave that loads the clock AND `sll v1,v1,k`'s the period
# (v1) before the `div zero,v0,v1`. @0x80041a04: lui v0,0x8018 / lw v0,0x2964(v0) / nop / div.
# (sll uses v1, not the just-loaded v0, so no load-delay nop is needed.)
FIREANIM_SIG = bytes.fromhex(
    "1880023c""6429428c""00000000""1a004300""02006014")
FIREANIM_REDIR_OFF = 0x04          # `lw v0,0x2964(v0)` (6429428c) -> j cave
FIREANIM_REDIR_OLD = "6429428c"
FIREANIM_JMP = 0x08020446          # j 0x80081118
FIREANIM_CAVE_VADDR = 0x80081118   # same 300-byte gap, past the gravity cave (ends 0x80081118)
#   cave: lui v0,0x8018 / lw v0,0x2964(v0) / sll v1,v1,k (period*N) / j 0x80041a10 / nop
FIREANIM_CAVE = {
    "quarter": [0x3c028018, 0x8c422964, 0x00031880, 0x08010684, 0x00000000],  # sll v1,v1,2 (*4)
    "half":    [0x3c028018, 0x8c422964, 0x00031840, 0x08010684, 0x00000000],  # sll v1,v1,1 (*2)
}

# --- WATER (and other scrolling textures) -- CLUT scroll engine (FUN_8003529x) ---
# Water shimmer is a palette/CLUT *scroll*: a scroll descriptor (s0) holds step(+1), position(+2,
# = 0x801aeb20, the 0..31 row offset), max(+0x14) and VRAM coords; each render frame it does
# `position += step` (wrap at max) then DMAs the scrolled CLUT to VRAM @(1008,96) via FUN_80079e90.
# At 60fps the scroll advances 4x too fast. Gate ONLY the position advance to every Nth frame
# (force step=0 on the other frames) -- the per-frame VRAM upload still runs (no flicker), the
# scroll just advances /N. This is the texture-scroll engine, NOT the character engine
# (FUN_80042eb0), so characters are unaffected. @0x80035278: lbu v1,1(s0)[step] / lhu v0,2(s0)
# [pos] / nop / addu a1,v1,v0. Redirect the step load to a cave that zeros step off-cadence.
WATERSCROLL_SIG = bytes.fromhex(
    "00004392""01000234""2b006214""00000000""01000392""02000296""00000000""21286200""00140500")
WATERSCROLL_REDIR_OFF = 0x10       # `lbu v1,1(s0)` (01000392) -> j cave
WATERSCROLL_REDIR_OLD = "01000392"
WATERSCROLL_JMP = 0x0802044b       # j 0x8008112c
WATERSCROLL_CAVE_VADDR = 0x8008112c  # same 300-byte gap, past the fire cave (ends 0x8008112c)
#   cave: lbu v1,1(s0) / lui a0,0x801b / lw a0,0x2580(a0) / nop / andi a0,a0,N-1 / beqz a0,keep
#         / nop / move v1,zero / [keep] j 0x80035284 / nop      (step=0 unless frame%N==0)
WATERSCROLL_CAVE = {
    "quarter": [0x92030001, 0x3c04801b, 0x8c842580, 0x00000000, 0x30840003, 0x10800002,
                0x00000000, 0x00001821, 0x0800d4a1, 0x00000000],   # frame & 3 -> advance ÷4
    "half":    [0x92030001, 0x3c04801b, 0x8c842580, 0x00000000, 0x30840001, 0x10800002,
                0x00000000, 0x00001821, 0x0800d4a1, 0x00000000],   # frame & 1 -> advance ÷2
}

# --- ENEMY DROP "4x loot" fix (death-state drop block in FUN_800500a8) ---
# On death, an enemy spawns ALL its loot (gold via FUN_80046294, items via FUN_800460bc) inside one
# block gated by the edge detector FUN_8004db98(enemy,0x800) @0x800506c0: it returns true while
# `timer - step <= 0x800 < timer`, where timer=obj[0x18] and step=obj[0x66] (last anim step, written
# by FUN_8004db3c). That is a correct ONE-shot edge *only when* step == the per-think advance. Our
# ENEMYANIM fix scales the advance (obj[0x18] += step>>N) but FUN_8004db3c still stores the FULL step
# in obj[0x66] -- so the edge "window" stays the full step (e.g. 0xa0) wide while the timer now
# creeps step>>N (e.g. 0x28) per think. The edge stays true for N consecutive thinks, so the whole
# drop block (gold + items, each rand-rolled) runs N times -> N x loot (the long-standing "4x drops"
# at 60 fps). Confirmed live: gold(FUN_80046294)+herb(FUN_800460bc) both fire 4x; timer steps 0x28.
# Fix: redirect THIS edge check (only this call site -- FUN_8004db98 is shared by attack states) to a
# cave that recomputes the crossing with the ACTUAL advance (step>>N, read live from obj[0x66]) and
# returns v0=1 only on the genuine crossing think -> the entire block runs exactly once. a0=enemy
# (addu a0,s3 just before), a1=0x800 (the jal delay slot, runs before the cave). Self-calibrating.
# @0x800506b4: addiu v0,v1,-0x200 / sh v0,0x16(s3) / addu a0,s3,zero / jal 0x8004db98 / ori a1,0x800
DROPEDGE_SIG = bytes.fromhex(
    "00fe6224""160062a6""21206002""e636010c""00080534")
DROPEDGE_OFF = 0x0c                 # the `jal 0x8004db98` (e636010c) -> jal cave
DROPEDGE_OLD = "e636010c"
DROPEDGE_JMP = 0x0c020455           # jal 0x80081154
DROPEDGE_CAVE_VADDR = 0x80081154    # same gap, immediately past the waterscroll cave (ends 0x80081154)
#   cave (mirrors FUN_8004db98 but window = step>>N instead of full step):
#     lhu t1,0x66(a0)[step] / lhu t0,0x18(a0)[timer] / sra t1,t1,N (advance) / subu t2,t0,t1 (prev)
#     / sltu t3,a1,t0 (thr<timer) / sltu t4,a1,t2 (thr<prev) / xori t4,t4,1 (prev<=thr)
#     / and v0,t3,t4 (=single-think crossing) / jr ra / nop
#   NOTE: timer load placed AFTER step load to fill the R3000 load-delay slot of `lhu t1` (so the
#   `sra t1` sees the real step). subu reads t0 two instrs after its load -> settled. a1 is the
#   threshold from the original delay slot (0x800) -- using it keeps the cave generic.
DROPEDGE_CAVE = {
    "quarter": [0x94890066, 0x94880018, 0x00094883, 0x01095023, 0x00a8582b,
                0x00aa602b, 0x398c0001, 0x016c1024, 0x03e00008, 0x00000000],  # sra,2
    "half":    [0x94890066, 0x94880018, 0x00094843, 0x01095023, 0x00a8582b,
                0x00aa602b, 0x398c0001, 0x016c1024, 0x03e00008, 0x00000000],  # sra,1
}

# --- FIELD OF VIEW (custom, optional --fov) -- the GTE projection distance H (cop2 ctrl reg 26)
# sets the FOV. The scene-init FUN_80035394 does gte_SetGeomOffset(160,120) (screen 320x240, so
# the projection centre/scale is 4:3) and gte_ldH(200) -> horizontal FOV = 2*atan(160/H), i.e.
# H=200 -> ~77.3deg (the game default). LOWER H = WIDER FOV (H=160 -> 90deg, H=128 -> ~102deg).
# H is loaded by the idiom `ori t0,zero,0xc8 / addu t4,t0,zero / ctc2 t4,H` at two sites in
# FUN_80035394 (set-once at scene load; fog FUN_80035358 reads the live H, so it stays consistent).
# We patch the 16-bit immediate (0x00c8) in BOTH occurrences. (Only applied when --fov is given;
# pairs with DuckStation's 16:9 display aspect. The widescreen edge-culling fix is separate.)
FOV_IDIOM = bytes.fromhex("c8000834" "21600001" "00d0cc48")  # li t0,200 / move t4,t0 / ctc2 t4,H(26)
FOV_OFX = 160                       # OFX = screen half-width; horizontal FOV = 2*atan(OFX/H)
FOV_H_DEFAULT = 200                 # the stock H (==0x00c8, the immediate we overwrite)


def _fov_to_h(deg):
    """Horizontal-FOV degrees -> GTE H (projection distance). Clamped to a sane 16-bit range."""
    h = round(FOV_OFX / math.tan(math.radians(deg) / 2.0))
    return max(24, min(0x3ff, h))


# --- WIDESCREEN CULLING (applied with --fov) -- the PVS (potentially-visible-set) builder
# FUN_80034bf4 marks which dungeon cells are visible by casting a view cone of half-angle 0x1b8
# (KF2 units, 0x1000 = 360deg -> 38.7deg half = 77.3deg total == the stock render FOV) across a
# 25x25 grid (DAT_801aec84). BOTH the wall renderer (FUN_8003bfd0) and the object renderer
# (FUN_80040694/FUN_80040708) draw only cells flagged visible there -- so with a wider FOV and/or
# a 16:9 display, cells in the new edge band stay unflagged and pop in/out. We widen the cone half-
# angle to cover the chosen FOV on a 16:9 display + a rotation margin. The angle is the immediate
# of `addiu s5,v0,0x1b8` @0x80034c80 (s5 = (pitch_term>>10) + 0x1b8); we rewrite the 0x01b8.
CULL_SIG = bytes.fromhex("ff034224" "83120200" "b8015524" "68db010c")  # addiu v0,0x3ff/sra/addiu s5,v0,0x1b8/jal
CULL_OFF = 0x08                     # the 16-bit immediate (0x01b8) of `addiu s5,v0,0x1b8`
CULL_STOCK = 0x01b8                 # 38.7deg half-angle == 77.3deg total (the stock view cone)

# --- CULL draw-distance limiter (0x258) -- the cone half-angle `s5`/iVar22 (FUN_80034bf4) is NOT a
# fixed value: it's `base + pitch_term`, where pitch_term >= 0 grows as you look up/down. The function
# has a DISCONTINUITY at 0x258: `if (iVar22 < 0x258) uVar21 = drawdist^2;  else uVar21 =
# drawdist^2 * cos(iVar22/2)` (the cos branch keeps a wide cone's lateral extent inside the fixed
# 25x25 PVS grid). The trap: if `base` sits NEAR 0x258, tiny pitch (camera bob / slight look up-down
# while walking) makes iVar22 cross 0x258 back and forth -> draw distance toggles full<->scaled ->
# edge geometry / skybox FLICKER and pop (the v36 bug: base 0x254 was right at the threshold).
# Two stable regimes only: base far BELOW 0x258 (the stock 0x1b8 -- too narrow for 16:9), or base
# AT/ABOVE 0x258 (always in the cos branch -> smooth, never crosses). 16:9 needs ~0x249, so we take
# the second: keep the cone >= 0x258 so it's ALWAYS cos-scaled. We do NOT touch the 0x258 constant
# (raising it re-creates the crossing; disabling it overruns the grid -- both flicker). The cost is
# the engine's own wide-cone trade: ~6% shorter center draw distance, but rock-stable.
CULL_LIMITER = 0x258                # cone half-angle at/above which the game cos-scales the distance


CULL_STOCK_FOV = 77.3               # stock horizontal FOV (H=200) -- used when culling w/o --fov


def _fov_to_cull_half(deg):
    """PVS cone half-angle (KF2 units) covering `deg` horizontal FOV on a 16:9 display + a margin.

    Clamped to be >= CULL_LIMITER (0x258) so the cone sits permanently in the game's cos-scaled
    branch: iVar22 = base + pitch_term (pitch_term >= 0) then never dips below the 0x258 threshold,
    so it never crosses the full<->scaled discontinuity and never flickers (see the note above).
    """
    half_deg = (deg / 2.0) * (4.0 / 3.0) + 5.0       # 16:9 widen (DuckStation WS) + ~5deg rotation margin
    units = round(half_deg * 4096.0 / 360.0)
    return max(CULL_LIMITER, min(0x3a0, units))      # >= limiter (always cos-scaled); cap < 90deg half


# --- FOG calibration H (applied with --fov) -- the GTE depth-cue fog (distant geometry fades to the
# near-black FarColor) is calibrated by FUN_80035358's `SetFogNear(a, 200)` @0x80035380. The 200 is
# the projection H the fog math assumes; the GTE actually projects with our patched H, so a changed
# FOV leaves the fog computed for the wrong H -> distant geometry under-fogged and popping at the
# wide edges. We rewrite this 0xc8 to match the render H so DQA/DQB track the real projection.
FOGH_SIG = bytes.fromhex("ffff0434" "b6de010c" "c8000534" "1000bf8f")  # li a0,-1/jal SetFogNear/li a1,200/lw ra
FOGH_OFF = 0x08                     # the 16-bit immediate (0xc8=200) of `ori a1,zero,0xc8`
FOGH_STOCK = 200

# --- BOTTOM-CORNER fix -- the PVS builder's NEAR band (`uVar9 < 5` cells, i.e. within ~2.2 of the
# camera) is drawn unconditionally-ish but STILL cone-tested, so floor/walls point-blank to the
# SIDES (the screen's bottom corners at a wide FOV, near 90deg) get culled. Two edits: (1) widen the
# near band `sltiu v0,v1,5` @0x80034ea4 to a bigger always-near radius; (2) NOP its two cone-check
# branches `bgtz a0` @0x80034eb0 / `bltz a1` @0x80034eb8 so the whole near disc is always drawn.
# @0x80034ea4: sltiu v0,v1,5 / beq / nop / bgtz a0,cull / nop / bltz a1,cull / li v0,0x1e
NEARBAND_SIG = bytes.fromhex(
    "0500622c" "07004010" "00000000" "1300801c" "00000000" "1100a004" "1e000234")
NEARBAND_THRESH_OFF = 0x00          # `sltiu v0,v1,5` immediate -> bigger near radius
NEARBAND_THRESH_NEW = 0x24          # dist^2 < 0x24 (~6 cells) always-near (covers point-blank corners)
NEARBAND_NOP1_OFF = 0x0c            # `bgtz a0,cull` -> nop
NEARBAND_NOP2_OFF = 0x14            # `bltz a1,cull` -> nop

# Note: the "far band" ring (cells `uVar9 < 0x100` beyond the visible band, drawn with no cone test)
# is deliberately LEFT ALONE. Straight ahead those cells are the black backdrop (huge forward-Z ->
# fully fogged) that hides the draw-distance edge; trimming them exposes the edge as center popping.
# The distant *side* popping (those same cells at a wide angle, where forward-Z is small so the
# depth fog can't reach them) is an inherent limit of KF2's forward-Z fog at a wide FOV.

# --- NOTIFICATION message display speed (3 byte edits, FUN @0x80042xxx) ---
# Bottom-screen messages (pre-rendered text textures) animate via a per-frame phase machine on
# bytes F7(phase)/F8(hold timer)/F9(ramp) @0x801aeaf7..f9:
#   appear : F9 += 0x14/frame until >=0x64   (@0x8004216c)
#   hold   : F8 (init 0x0F @0x80042024) -= 1/frame until 0   (@0x800421a4)
#   disappear: F9 += 0xec (= -0x14)/frame until 0   (@0x800421d0)
# Total ~25 frames -> 0.4s at 60fps (4x too fast). Slow each phase /N: ramp step /N, hold init xN.
# 0x64 is divisible by the new steps so F9 still lands exactly on 0x64/0 (no overshoot).
MSG_HOLD_SIG = bytes.fromhex("0000c2a0""0f000234""1b80013c""f8ea22a0")
MSG_HOLD_OFF = 0x04            # `ori v0,zero,0xf` immediate (F8 hold frames) -> xN
MSG_HOLD_OLD = 0x0f
MSG_HOLD_NEW = {"quarter": 0x3c, "half": 0x1e}
MSG_APPEAR_SIG = bytes.fromhex("1b80023c""f9ea4290""00000000""14004224""1b80013c""f9ea22a0")
MSG_APPEAR_OFF = 0x0c          # `addiu v0,v0,0x14` step (F9 ramp up) -> /N
MSG_APPEAR_OLD = 0x14
MSG_APPEAR_NEW = {"quarter": 0x05, "half": 0x0a}
MSG_DISAPPEAR_SIG = bytes.fromhex("1b80023c""f9ea4290""00000000""ec004224""1b80013c""f9ea22a0")
MSG_DISAPPEAR_OFF = 0x0c       # `addiu v0,v0,0xec` (= -0x14) step (F9 ramp down) -> -0x14/N
MSG_DISAPPEAR_OLD = 0xec
MSG_DISAPPEAR_NEW = {"quarter": 0xfb, "half": 0xf6}   # -5 (quarter), -10 (half)

# --- ITEM PICKUP spin (FUN_8005d.. item-display sub-loop @0x8005dfc4) ---
# When you pick up an item it spins its 3D model in the center of the screen. The sub-loop renders
# via FUN_800422b8 (frame-capped at 60fps), and advances the rotation angle (item struct +0x26 =
# 0x801929a6) by `addiu v0,v0,0x40` (+0x40/frame). At 60fps that's 4x the original 15fps spin.
# One byte edit: step 0x40 -> 0x10 (÷4). (The cancel "faster spin" uses the same writer, so it
# scales with it.)  @0x8005dfb4: lw v1,0x80(sp) / lhu v0,0x26(v1) / addiu v0,v0,0x40 / sh v0,0x26.
ITEMSPIN_SIG = bytes.fromhex(
    "8000a38f""00000000""26006294""21902002""40004224""9256000c""260062a4")
ITEMSPIN_OFF = 0x10            # `addiu v0,v0,0x40` step immediate (low byte) -> /N
ITEMSPIN_OLD = 0x40
ITEMSPIN_NEW = {"quarter": 0x10, "half": 0x20}

# The same item-pickup sub-loop has 3 more per-frame steps (16-bit immediates) -- all /N:
#   move-to-center   @0x8005df5c  addiu s0,s0,0x200   (s0 lerps 0->0x1000)
#   cancel/take fast-spin @0x8005e184  addiu v0,v0,0x100  (4x the steady spin)
#   move-out/return  @0x8005e26c  addiu s0,s0,-0x200  (s0 lerps 0x1000->0)
ITEM_IMM_EDITS = (
    # (name, sig, off, old_u16, {quarter, half})
    ("item-movein",
     bytes.fromhex("21300002""8000a38f""00021026""5c5c000c""0e0062a4"), 0x08, 0x0200,
     {"quarter": 0x0080, "half": 0x0100}),
    ("item-fastspin",
     bytes.fromhex("26006294""feff0526""00014224""ff0f4230""ae08010c"), 0x08, 0x0100,
     {"quarter": 0x0040, "half": 0x0080}),
    ("item-moveout",
     bytes.fromhex("21284002""8000a38f""00fe1026""ae08010c""0e0062a4"), 0x08, 0xfe00,
     {"quarter": 0xff80, "half": 0xff00}),   # -0x200 -> -0x80 / -0x100
)

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


def apply_patches(data, mode, fov=None, cull=None, bob="on"):
    """Apply all 60 fps patches to `data` (a bytearray) in place. Returns nothing.

    `fov` (optional) = custom horizontal field of view in degrees; rewrites the GTE H immediate.
    `cull` (optional) = widescreen edge-culling fix: True/False to force, None = auto (on iff fov).
    `bob`  = head-bob: "on" (default) = run at the correct (scaled) speed; "off" = disabled."""
    c = find_once(data, CAP_SIG, "cap")
    for off in CAP_OFF:
        assert data[c + off] == 0x04, "cap byte mismatch"
        data[c + off] = CAP_NEW[mode]
    print("CAP        @0x%X,0x%X  cap 4->%d" % (c + CAP_OFF[0], c + CAP_OFF[1], CAP_NEW[mode]))

    if bob == "off":
        b = find_once(data, BOB_SIG, "bob")
        assert data[b + BOB_OFF] == 0x22, "bob byte mismatch"
        data[b + BOB_OFF] = 0x20
        print("BOB        @0x%X  head-bob OFF (output zeroed)" % (b + BOB_OFF))
    else:
        bf = find_once(data, BOBFIX_SIG, "bobfix")
        data[bf:bf + len(BOBFIX_NEW[mode])] = BOBFIX_NEW[mode]
        print("BOB        @0x%X  head-bob phase /%d (correct-speed bob)" % (
            bf, 4 if mode == "quarter" else 2))

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

    # LOOK (vertical / pitch): scale the per-frame pitch advance at both apply sites (up + down).
    for nm, sig in (("look_up", LOOK_UP_SIG), ("look_dn", LOOK_DN_SIG)):
        li = find_once(data, sig, nm)
        assert int.from_bytes(data[li + LOOK_OFF:li + LOOK_OFF + 4], "little") == LOOK_OLD, \
            "%s byte mismatch" % nm
        data[li + LOOK_OFF:li + LOOK_OFF + 4] = LOOK_NEW[mode].to_bytes(4, "little")
        print("LOOK       @0x%X  %s  addu v1,v0,zero -> sra v1,v0,%d (vertical camera /%d)" % (
            li + LOOK_OFF, nm, 2 if mode == "quarter" else 1, 4 if mode == "quarter" else 2))

    pz = find_once(data, POISON_SIG, "poison")
    assert int.from_bytes(data[pz + POISON_DIV_OFF:pz + POISON_DIV_OFF + 4], "little") == POISON_DIV_OLD \
        and int.from_bytes(data[pz + POISON_MUL_OFF:pz + POISON_MUL_OFF + 4], "little") == POISON_MUL_OLD, \
        "poison byte mismatch"
    data[pz + POISON_DIV_OFF:pz + POISON_DIV_OFF + 4] = POISON_DIV_NEW[mode].to_bytes(4, "little")
    data[pz + POISON_MUL_OFF:pz + POISON_MUL_OFF + 4] = POISON_MUL_NEW[mode].to_bytes(4, "little")
    print("POISON     @0x%X  tick modulus 30->%d (poison/DoT /%d)" % (
        pz, 120 if mode == "quarter" else 60, 4 if mode == "quarter" else 2))

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
    inject("fireanim", FIREANIM_SIG, FIREANIM_REDIR_OFF, FIREANIM_REDIR_OLD, FIREANIM_JMP,
           FIREANIM_CAVE_VADDR, FIREANIM_CAVE[mode])
    inject("waterscroll", WATERSCROLL_SIG, WATERSCROLL_REDIR_OFF, WATERSCROLL_REDIR_OLD,
           WATERSCROLL_JMP, WATERSCROLL_CAVE_VADDR, WATERSCROLL_CAVE[mode])
    inject("dropedge", DROPEDGE_SIG, DROPEDGE_OFF, DROPEDGE_OLD, DROPEDGE_JMP, DROPEDGE_CAVE_VADDR,
           DROPEDGE_CAVE[mode])

    # GRAVITY: redirect the velocity load to a >>k cave AND divide the accel immediate. Found once
    # (both sites still original at find time), then both edits applied -- so no re-find needed.
    gi = find_once(data, GRAV_SIG, "gravity")
    assert data[gi + GRAV_REDIR_OFF:gi + GRAV_REDIR_OFF + 4] == bytes.fromhex(GRAV_REDIR_OLD), \
        "gravity redirect byte mismatch"
    assert data[gi + GRAV_INC_OFF] == 0x28, "gravity accel byte mismatch"
    gcbin = base + _bin_off(_file_off(GRAV_CAVE_VADDR))
    assert all(x == 0 for x in data[gcbin:gcbin + 4 * len(GRAV_CAVE[mode])]), "gravity cave not free"
    data[gi + GRAV_REDIR_OFF:gi + GRAV_REDIR_OFF + 4] = GRAV_JMP.to_bytes(4, "little")
    data[gi + GRAV_INC_OFF] = GRAV_INC_NEW[mode]
    for k, word in enumerate(GRAV_CAVE[mode]):
        data[gcbin + 4 * k:gcbin + 4 * k + 4] = word.to_bytes(4, "little")
    print("GRAVITY    @0x%X redirect + accel 0x28->0x%02x -> cave @bin0x%X (vaddr 0x%X)" % (
        gi + GRAV_REDIR_OFF, GRAV_INC_NEW[mode], gcbin, GRAV_CAVE_VADDR))

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

    # NOTIFICATION message display speed: slow the 3-phase appear/hold/disappear animation /N.
    for name, sig, off, old, new in (
            ("msg-hold", MSG_HOLD_SIG, MSG_HOLD_OFF, MSG_HOLD_OLD, MSG_HOLD_NEW[mode]),
            ("msg-appear", MSG_APPEAR_SIG, MSG_APPEAR_OFF, MSG_APPEAR_OLD, MSG_APPEAR_NEW[mode]),
            ("msg-disappear", MSG_DISAPPEAR_SIG, MSG_DISAPPEAR_OFF, MSG_DISAPPEAR_OLD,
             MSG_DISAPPEAR_NEW[mode])):
        idx = find_once(data, sig, name)
        assert data[idx + off] == old, "%s byte mismatch" % name
        data[idx + off] = new
        print("MSG %-13s @0x%X  0x%02x -> 0x%02x" % (name, idx + off, old, new))

    # ITEM PICKUP spin speed: scale the rotation step.
    isp = find_once(data, ITEMSPIN_SIG, "itemspin")
    assert data[isp + ITEMSPIN_OFF] == ITEMSPIN_OLD, "itemspin byte mismatch"
    data[isp + ITEMSPIN_OFF] = ITEMSPIN_NEW[mode]
    print("ITEM-SPIN @0x%X  step 0x40 -> 0x%02x" % (isp + ITEMSPIN_OFF, ITEMSPIN_NEW[mode]))
    for name, sig, off, old_u16, new in ITEM_IMM_EDITS:
        idx = find_once(data, sig, name)
        assert int.from_bytes(data[idx + off:idx + off + 2], "little") == old_u16, \
            "%s imm mismatch" % name
        data[idx + off:idx + off + 2] = new[mode].to_bytes(2, "little")
        print("%-14s @0x%X  0x%04x -> 0x%04x" % (name, idx + off, old_u16, new[mode]))

    # FOV (optional, --fov): rewrite the GTE H immediate in every gte_ldH(200) site (both in the
    # scene-init FUN_80035394), and recalibrate the depth-cue fog H to match. Skipped unless --fov.
    if fov is not None:
        h = _fov_to_h(fov)
        n_fov, start = 0, 0
        while True:
            idx = data.find(FOV_IDIOM, start)
            if idx < 0:
                break
            assert data[idx:idx + 2] == FOV_H_DEFAULT.to_bytes(2, "little"), "fov H imm mismatch"
            data[idx:idx + 2] = h.to_bytes(2, "little")
            n_fov += 1
            start = idx + len(FOV_IDIOM)
        if n_fov == 0:
            raise SystemExit("ERROR: FOV H-load idiom not found (wrong dump?)")
        eff = 2 * math.degrees(math.atan(FOV_OFX / h))
        print("FOV        %d site(s)  H %d->%d  (~%.1f deg horizontal)" % (
            n_fov, FOV_H_DEFAULT, h, eff))

        # Recalibrate the depth-cue fog for the new projection H (else distant geometry pops).
        fi = find_once(data, FOGH_SIG, "fogh")
        assert data[fi + FOGH_OFF:fi + FOGH_OFF + 2] == FOGH_STOCK.to_bytes(2, "little"), \
            "fogh imm mismatch"
        data[fi + FOGH_OFF:fi + FOGH_OFF + 2] = h.to_bytes(2, "little")
        print("FOG-H      @0x%X  %d->%d  (match projection so depth fog tracks the FOV)" % (
            fi + FOGH_OFF, FOGH_STOCK, h))

    # WIDESCREEN CULLING (--cull wins; otherwise auto-on when --fov is set). Widens the PVS view
    # cone + near band and trims the far ring so walls/objects/floor stop popping at the 16:9 edges.
    do_cull = cull if cull is not None else (fov is not None)
    if do_cull:
        eff_fov = fov if fov is not None else CULL_STOCK_FOV
        half = _fov_to_cull_half(eff_fov)
        ci = find_once(data, CULL_SIG, "cull")
        assert data[ci + CULL_OFF:ci + CULL_OFF + 2] == CULL_STOCK.to_bytes(2, "little"), \
            "cull imm mismatch"
        data[ci + CULL_OFF:ci + CULL_OFF + 2] = half.to_bytes(2, "little")
        print("CULL       @0x%X  PVS half-angle 0x%x->0x%x  (~%.0f deg cone, 16:9 of %.0f deg FOV)" % (
            ci + CULL_OFF, CULL_STOCK, half, half * 360.0 / 4096.0 * 2, eff_fov))

        # Bottom corners: widen the always-near disc + NOP its cone-check branches.
        ni = find_once(data, NEARBAND_SIG, "nearband")
        assert data[ni + NEARBAND_THRESH_OFF] == 0x05, "nearband thresh mismatch"
        data[ni + NEARBAND_THRESH_OFF:ni + NEARBAND_THRESH_OFF + 2] = \
            NEARBAND_THRESH_NEW.to_bytes(2, "little")
        data[ni + NEARBAND_NOP1_OFF:ni + NEARBAND_NOP1_OFF + 4] = bytes(4)
        data[ni + NEARBAND_NOP2_OFF:ni + NEARBAND_NOP2_OFF + 4] = bytes(4)
        print("NEAR-BAND  @0x%X  near radius 5->0x%x + cone check nop (point-blank corners)" % (
            ni + NEARBAND_THRESH_OFF, NEARBAND_THRESH_NEW))
        print("  cone half 0x%x >= 0x%x limiter -> always cos-scaled (stable, no pitch-crossing "
              "flicker; ~6%% shorter center draw distance is the engine's wide-cone trade-off)" % (
                  half, CULL_LIMITER))

        # (We deliberately leave the 0x258 limiter alone and keep the cone >= it so iVar22 stays in
        # the cos-scaled branch for ALL camera pitches -- no full<->scaled crossing -> no flicker.
        # Disabling it (v35) overran the 25x25 grid; sitting it at the threshold (v36) flickered.
        # The remaining distant *side* popping at wide --fov is inherent to KF2's forward-Z fog.)


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
    ap.add_argument("--version", action="version", version="kf2-60fps %s" % VERSION)
    ap.add_argument("input", help="path to your King's Field II (USA) .bin (MODE2/2352)")
    ap.add_argument("output", help="path to write the patched .bin")
    ap.add_argument("--mode", choices=("quarter", "half"), default="quarter",
                    help="quarter = 60 fps + 1/4 speed (default); half = 30 fps + 1/2 speed")
    ap.add_argument("--bps", metavar="patch.bps",
                    help="also write a shareable BPS patch (contains only our edits)")
    ap.add_argument("--fov", type=float, default=None, metavar="DEG",
                    help="[EXPERIMENTAL] custom horizontal field of view in degrees (game default "
                         "~77; e.g. 90/100). Lower H/wider FOV (both axes). KNOWN ISSUE: at a wide "
                         "FOV, distant geometry at the far left/right can't be fully fogged (KF2's "
                         "fog is forward-Z based) and may pop. Recommended widescreen mode is the "
                         "stock FOV + --cull on. See docs/RESEARCH.md sec.13.")
    ap.add_argument("--cull", choices=("on", "off"), default=None,
                    help="[EXPERIMENTAL] widescreen edge-culling fix (widen the PVS view cone so "
                         "walls/objects stop popping at the 16:9 edges; also fixes the bottom "
                         "corners). Default: on when --fov is set, else off. An explicit --cull "
                         "on/off overrides that. Known limitation: the cone is bounded by KF2's "
                         "fixed visibility grid, so a small rotation margin remains and edge "
                         "geometry can pop slightly during fast turns.")
    ap.add_argument("--bob", choices=("on", "off"), default="on",
                    help="head-bob (camera bob while walking). on (default) = runs at the correct "
                         "original speed (scaled for 60fps); off = disabled entirely (the camera "
                         "stays level). Default: on.")
    ap.add_argument("--no-crc-check", action="store_true",
                    help="skip the source size/CRC verification")
    args = ap.parse_args(argv)
    print("King's Field II (USA) 60 FPS patcher  v%s" % VERSION)
    if args.fov is not None and not (40.0 <= args.fov <= 150.0):
        ap.error("--fov must be between 40 and 150 degrees")
    cull = None if args.cull is None else (args.cull == "on")

    source = bytearray(open(args.input, "rb").read())

    if not args.no_crc_check:
        crc = "%08X" % (zlib.crc32(source) & 0xffffffff)
        md5 = hashlib.md5(source).hexdigest()
        sha1 = hashlib.sha1(source).hexdigest()
        mism = (len(source) != SRC_SIZE or crc != "%08X" % SRC_CRC32
                or md5 != SRC_MD5 or sha1 != SRC_SHA1)
        if mism:
            print("WARNING: input does not match the known King's Field II (USA) dump (%s)" % SRC_SERIAL)
            print("  expected size=%d crc32=%s" % (SRC_SIZE, "%08X" % SRC_CRC32))
            print("           md5=%s sha1=%s" % (SRC_MD5, SRC_SHA1))
            print("  got      size=%d crc32=%s" % (len(source), crc))
            print("           md5=%s sha1=%s" % (md5, sha1))
            print("  (continuing; patches are signature-located. Use --no-crc-check to silence.)")
        else:
            print("VERIFIED   %s  size/crc32/md5/sha1 all match" % SRC_SERIAL)

    data = bytearray(source)
    apply_patches(data, args.mode, args.fov, cull, args.bob)
    open(args.output, "wb").write(data)
    print("wrote %s (%d bytes), mode=%s%s%s%s" % (
        args.output, len(data), args.mode,
        "" if args.fov is None else (", fov=%g deg" % args.fov),
        "" if args.cull is None else (", cull=%s" % args.cull),
        "" if args.bob == "on" else ", bob=off"))

    if args.bps:
        bps = make_bps(bytes(source), bytes(data))
        open(args.bps, "wb").write(bps)
        print("wrote %s (%d bytes BPS patch -- shareable, no game code)" % (args.bps, len(bps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
