# King's Field II (USA) — 60 FPS reverse-engineering notes

All addresses are GAME.EXE virtual addresses (loaded at `0x80011000`) unless noted.
GAME.EXE header: `pc0=0x800144F8`, `t_addr=0x80011000`, `t_size=0x8B800`. Source disc:
Redump *King's Field II (USA)*, raw `MODE2/2352`, 571,766,496 bytes, CRC32 `F8A4C585`.

## 1. The framerate model

KF2 advances all game logic **once per rendered frame** (movement is `pos += velocity`
per frame, animations advance per frame, etc.), and the display swap is vblank-locked.
The game also has an explicit cap: it waits **4 vblanks per frame** (`FUN_80019614`), so
it renders at ~15 FPS. Logic is *not* time-based, so:

- Removing the cap → the game renders faster but everything runs ~4× too fast.
- The fix is to cap at exactly **60 FPS** (1 vblank/frame) and scale every per-frame
  system by **÷4**. Because the cap is fixed, the result is **portable** across any
  sufficient overclock value — the game can't exceed 60 FPS, so the ÷4 scaling is always
  correct. (Constant ÷4 scaling only works for *constant-velocity* systems; acceleration
  systems like gravity need different handling — see §6.)

## 2. How the patcher works

The patcher edits a raw `MODE2/2352` `.bin` in place. Each site is located by a **code
signature** (a short, unique byte pattern), not a hardcoded offset, so it's robust. Two
kinds of edit:

- **Same-size byte edits** — change an immediate or a register field (CAP, BOB, WALK,
  TURN, MAGIC-DELAY).
- **Code-cave injection** — redirect one instruction to a small routine written into
  unused padding inside GAME.EXE, then jump back (ENEMY, ATTACK-BAR, MAGIC). Used when
  there's no free inline slot to do the scaling.

### MODE2/2352 offset mapping

A raw `MODE2/2352` sector is 2352 bytes containing 2048 user bytes (+ sync/header/EDC/ECC).
So a GAME.EXE file offset `F` maps to a raw `.bin` offset of
`P + F + (F // 2048) * 304`, where `P` is the `.bin` offset of GAME.EXE's first byte
(found via the `PS-X EXE` magic / a known-vaddr signature). vaddr → file offset is
`(vaddr - 0x80011000) + 0x800`. Short signatures stay within one sector's 2048-byte data
window, so a plain byte search finds them; only cross-sector cave writes need the formula.

## 3. Techniques

- **Finding a safe code cave.** *"Zero in the GAME.EXE file" does not mean free at
  runtime* — the game initializes data/tables into some zero regions at boot. A safe cave
  must be (a) zero in the file, (b) **inter-function padding flanked by real file-code**
  (so the game never uses it), and (c) actually loaded — *end-of-text padding is NOT
  loaded* (it's past the disc-recorded extent). Verify the **free run length in the file**
  (not just runtime) before placing a cave.

- **Round-half-away ÷N** (enemy velocity). A plain arithmetic shift truncates toward −∞,
  so small/diagonal velocities lose precision (e.g. `vx=6 → 1` instead of `1.5`) and slow
  movers crawl. The cave instead adds `±N/2` by sign before shifting, recovering the loss
  symmetrically.

- **Frame-gate** (recharge timers). To make a per-frame action happen only every Nth
  frame, fold a counter test into existing control flow (or jump to a cave that does it),
  so the action is skipped on `N-1` of every `N` frames.

- **Self-counter gate** (more robust). Some candidate "frame clocks" in RAM read
  inconsistently depending on where in the frame you sample them. The robust gate keeps
  its **own counter byte** in cave padding, increments it each call, and gates on
  `counter & (N-1)` — independent of any game clock.

## 4. Per-system details

### CAP — frame cap (`FUN_80019614`)
`while (vblank_ctr < 4) VSync(0);`. Two `sltiu v0,v0,0x4` immediates: change `4 → 1`
(60 FPS) or `4 → 2` (30 FPS). This caps the framerate (it does *not* fully uncap), which
is what makes the ÷4 scaling portable.

### BOB — cosmetic head-bob (`FUN_8002ed60`)
The walk bob-offset store `sh v0,0x2650(at)` → `sh zero,...` zeroes the cosmetic bob.
(Separate from floor-following; the bob's proper ÷4 needs injection and is deferred.)

### WALK / TURN — player movement
- Walk: `FUN_8002e3f8` computes `disp = dir * speed >> 0xc`. Change both shift amounts
  `>>0xc → >>0xe` (÷4) / `>>0xd` (÷2). Player position vars: `X=DAT_801b25f0`,
  `Z=DAT_801b25f8`, facing `DAT_801b2612`.
- Turn: scale the turn-max base in `FUN_80030fcc` (`ori v0,zero,0x20`/`,0x28`).

### ENEMY movement — cave (`FUN_8004dbc8`)
All enemy movement funnels through `FUN_8004dbc8`, which loads per-frame velocity
(`vx=s3`, `vz=s0`) then does `enemy.pos += vx/vz`. There's no inline slot, so the
`move s7,s3` is redirected to a cave that **round-half-away ÷N**'s `vx/vz`, redoes the
register copies, and jumps back. One injection scales every enemy.

### ATTACK-BAR — weapon charge (`DAT_801b2502`, in `FUN_8002d2a0`)
The idle recharge (delay timer `0x24f3` countdown + charge fill) runs every frame and sits
behind a gate `bne v0,zero,...` where `v0 = (0x265c & 0x1870)`. The cave **folds the frame
clock into that gate** so the whole recharge (delay + fill) runs only every Nth frame.

### MAGIC stamina gauge — (`DAT_801b2506`, must be `5000` to cast)
Filled by `0x2506 += sVar3` per frame in `FUN_8002fe1c`. The game clock reads unreliably
here, so the cave uses a **self-counter** and gates the fill every Nth call.

### PLAYER SWING animation — cave (`FUN_8002d2a0`)
A normal melee swing advances the arc `DAT_801b25a4 += s2` per frame (s2 = weapon
swing-speed `weapon[0x1c]`/`[0x24]`) until it reaches `0xfff`, then ends. At 60 fps the
arc completes 4× too fast. The advance instruction's delay slot is a branch (can't redirect
there), so we redirect the arc load `lhu v0,0x0(s0)` (@`0x8002d814`, safe delay slot) to a
cave that re-loads the arc and `sra`'s **s2 ÷N**. Scaling s2 (not the arc directly) keeps it
consistent with the hit-detection windows (`25a8 <= 25a4 < 25a8 + s2`), which also use s2 —
so the swing is N× slower and hits still register exactly once. (Note: `0x25a4` is also the
*special*-attack charge progress, advanced in a different branch — patched separately.)

### ENEMY / NPC animation — `FUN_8004db3c`
The shared per-object animation-phase advance: `obj[0x18] += step` (clamped `[0,0xfff]`;
step from object data, sign stored at `obj+0x66`), called per-frame for every object in the
update loop `FUN_800500a8`. At 60 fps all near-object animations (walk/idle/attack) run 4×
fast. There is a load-delay `nop` at `0x8004db5c`, right before the advance `addu v0,v1,v0`
(v1 = step); replace it with `sra v1,v1,N` to ÷N the step. Hit triggers use FIXED phase
thresholds (not the step), so they still fire correctly — the animation just runs N× slower.
This one instruction covers near enemies **and** NPCs.

### DISTANT (LOD) enemy animation — `FUN_8004db08`
*Distant* enemies (`obj[6]==2`) animate through a separate, simplified sibling of
`FUN_8004db3c`: `obj[0x18] = (obj[0x18] + step) & 0xfff` (this one *wraps* at `0xfff`
rather than clamping). It has the same shape — a load-delay `nop` at `0x8004db28`, right
before the advance `addu v0,v1,v0` (v1 = step) — so it takes the same fix: `nop` →
`sra v1,v1,N`. Frame-stepping a far object's phase confirmed the advance dropped from
+128/frame to +32/frame (÷4). With both `FUN_8004db3c` (near) and `FUN_8004db08` (far)
patched, enemy model animation is correct at all distances.

### MAGIC-DELAY — refill delay (`DAT_801b24f4`)
The magic recharge has a *delay* timer that, unlike the attack delay, decrements ungated —
so the magic bar started refilling 4× too soon. Its set value `60` is multiplied ×N
(→240) so the delay lasts as long as the (gated) attack delay and both bars start
refilling together. *(Note: MP itself does not passively regenerate in KF2 — only the
weapon/magic charge gauges do; "magic regen" refers to that gauge.)*

## 5. Automation tooling

Reverse engineering used [PCSX-Redux](https://github.com/grumpycoders/pcsx-redux)
(interpreter, with its Web API on `:8080` and GDB server on `:3333`) and Ghidra.

- **Deterministic frame-stepping** (`tools/redux_framestep.py`): set a GDB `Z0` breakpoint
  on the once-per-frame sync function and "continue" once per frame, reading any memory
  each frame. (`Z2` *watchpoints* don't fire reliably on this build; `Z0` does.) Supports
  `poke=ADDR:HEXBYTES` to write a value inside the paused loop, so per-frame rates of any
  counter can be measured with no game clock dependence.
- **Per-frame struct diff** (`tools/redux_framewatch.py`): frame-step and report which
  2-byte fields change — finds animation phases / timers in a struct.
- **Live poke / watch / RAM diff** (`tools/redux_pokew.py`, `redux_watchpoint.py`,
  `redux_ramdiff.py`).
- **Ghidra scripts** (`tools/ghidra/*.java`): xref a data address and decompile its
  referencers; decompile / disassemble a function or range. Base-relative stores
  (`sh rX,off(base)`) are invisible to an absolute-address xref, so the owning function is
  found by decompiling and reading the actual code.

## 6. Open / in progress

- **Enemy turning / rotation rate** — far enemies appear to *rotate* (turn to face the
  player) too fast; the model animation is correct but the facing-angle slew per frame is
  not yet scaled. Likely a separate per-frame `angle += turn_step` distinct from movement.
- **Water / scrolling-texture animation** — likely a per-frame UV/texture-page advance,
  separate from model animation.
- **Enemy attack timing** (largely covered by the animation phase), **menu speed**
  (input repeat + animation).
- **Doors / world animations.**
- **Acceleration physics** (vertical camera / gravity) — N² integration means a constant
  ÷4 is wrong; needs a code-cave with proper rescaling. The proper bob ÷4 is in this class.

## 7. Key addresses

| Name | Address | Notes |
| --- | --- | --- |
| Frame cap fn | `FUN_80019614` | once-per-frame vblank wait (frame-step breakpoint) |
| Player X / Z | `0x801b25f0` / `0x801b25f8` | |
| Player facing | `0x801b2612` | |
| Enemy move fn | `FUN_8004dbc8` | `enemy.pos += vx(s3)/vz(s0)` |
| Attack charge | `0x801b2502` | 0..5000 |
| Attack delay timer | `0x801b24f3` | |
| Magic charge | `0x801b2506` | 0..5000, full to cast |
| Magic delay timer | `0x801b24f4` | |
| Magic fill fn | `FUN_8002fe1c` | `0x2506 += sVar3` @ `0x80030220` |
| Controller buffer | `0x80007572` | active-low (Up = bit `0x10` clear) |
| Code-cave gaps | `0x8007EF80`, `0x80081078` | inter-function padding, file-verified free |
