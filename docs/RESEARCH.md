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

### ENEMY TURNING / facing slew — `FUN_8004e928`
Every turning AI state (chase, search, reorient) funnels through one "rotate toward a target
angle" routine. It's an *accelerating* turn: an angular velocity `obj[0x58]` ramps by
`±accel` each frame, clamped to `±maxrate`, then the facing yaw advances
`obj[0x42] += obj[0x58]`, with a snap-to-target when it overshoots. At 60 fps every enemy
turns 4× fast. The yaw is **not** a per-frame snap to the player's bearing — measured live,
an enemy's yaw moved −148 units while the bearing to the player changed only +17, confirming
a fixed-rate slew independent of player position. (This is also why turning looked worse at a
distance: distant enemies are usually the ones actively reorienting.)
The per-frame advance is `lhu v0,0x58(s0)` / `lh v1,0x58(s0)` / `addu v0,v0,a1` /
`sh v0,0x42(s0)`. We redirect the `lhu` to a cave that advances by `velocity/N` instead —
`sra v0,v1,N` using the already-loaded **signed** copy (`v1`) so negative turn rates shift
correctly — then rejoins before the `blez`/store. The accel ramp and snap-to-target are
untouched, so enemies still end up facing the player; they just turn N× slower. One injection
covers every enemy and NPC at all distances. (The angular velocity is left full-rate; only
the position advance is scaled — the brief accel ramp is visually negligible next to the
steady max-rate turn, like the constant-÷ approximation used elsewhere.)
**Tooling note:** found by live-capturing a moving+turning enemy's yaw/position synced with
the player's (GDB frame-step), ruling out the bearing-snap path, then static decompilation
(`FUN_800500a8` → `FUN_8004ea7c` → `FUN_8004e928`). Data write-watchpoints (Z2) don't fire
on this build, so the writer couldn't be trapped directly.

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
- **Memory write-watchpoint** (`tools/redux_watchpoint.lua`): GDB `Z2`/`Z4` data watchpoints
  do **not** fire on this build, but PCSX-Redux's native Lua `PCSX.addBreakpoint(addr,'Write',…)`
  does. A *custom invoker* overrides the default pause, so it logs the distinct writer PCs of an
  address **without freezing the game**, to a file. The reliable way to find "what writes X". A
  variant that restores a captured value on each write gives a non-pausing **freeze** for "does
  X drive this effect?" tests. (See §8 for how this was used.)
- **Ghidra scripts** (`tools/ghidra/*.java`): xref a data address and decompile its
  referencers; decompile / disassemble a function or range. Base-relative stores
  (`sh rX,off(base)`) are invisible to an absolute-address xref, so the owning function is
  found by decompiling and reading the actual code.

## 6. Open / in progress

- **Water / scrolling-texture animation** — *investigated deeply, deferred (engine-limited).*
  Goal: slow all animated/scrolling textures ÷4. Conclusion: the animation is computed
  **inline in the per-frame GTE / display-list build**, with **no tweakable RAM scroll
  counter** to scale — so there is no clean one-instruction lever like every other system had.
  See §8 for the full investigation and dead ends; revisit only with GPU/display-list-level
  tooling.
- **Enemy attack timing** (largely covered by the animation phase), **menu speed**
  (input repeat + animation).
- **Doors / world animations** — *mechanism mapped, fix is multi-site (see §9).* Doors are a
  **timed state machine** in `FUN_80047010` (the interactive-world-object dispatcher, separate
  from the enemy update). A naive ÷4 of the open/close ramp makes the door move smoothly but
  only travel ¼ of the way, because the open *phase length* is fixed by a per-frame state timer
  — the timer must be stretched 4× too. Deferred pending a focused multi-edit/cave pass.
- **Acceleration physics** (vertical camera / gravity) — N² integration means a constant
  ÷4 is wrong; needs a code-cave with proper rescaling. The proper bob ÷4 is in this class.

## 7. Key addresses

| Name | Address | Notes |
| --- | --- | --- |
| Frame cap fn | `FUN_80019614` | once-per-frame vblank wait (frame-step breakpoint) |
| Player X / Z | `0x801b25f0` / `0x801b25f8` | |
| Player facing | `0x801b2612` | |
| Enemy move fn | `FUN_8004dbc8` | `enemy.pos += vx(s3)/vz(s0)` |
| Enemy turn slew | `FUN_8004e928` | `obj[0x42] += obj[0x58]`; yaw `obj+0x42`, ang.vel `obj+0x58` |
| Attack charge | `0x801b2502` | 0..5000 |
| Attack delay timer | `0x801b24f3` | |
| Magic charge | `0x801b2506` | 0..5000, full to cast |
| Magic delay timer | `0x801b24f4` | |
| Magic fill fn | `FUN_8002fe1c` | `0x2506 += sVar3` @ `0x80030220` |
| Controller buffer | `0x80007572` | active-low (Up = bit `0x10` clear) |
| Code-cave gaps | `0x8007EF80`, `0x80081078` | inter-function padding, file-verified free |

## 8. Water / animated-texture investigation (deferred)

**Goal:** scale *all* animated/scrolling textures (water, and any UV-scrolling surfaces) by
÷4 so they animate at the original speed at 60 fps.

**Conclusion:** unlike every other system, there is **no single RAM value or instruction** to
scale. The texture animation is produced **inline in the per-frame GTE / display-list build**:
each frame the renderer rebuilds the GPU primitives (vertices + texture coords) for the visible
world, and any scroll/animation is baked into that rebuild via GTE math — not read from a
persistent, tweakable counter. So the ÷4 techniques that worked elsewhere (scale a step, gate a
counter, redirect one load) have nothing to attach to. Revisit only with GPU/display-list-level
tooling (e.g. a GPU command-stream inspector, or instrumenting the OT build).

**Dead ends (so a future attempt doesn't repeat them):**

1. **`0x8009EDxx` "counters" → sound-voice LRU, not textures.** A cluster of 5 values
   (stride `0x34`) ticked ~per-frame and looked like animated-texture frame indices. A
   write-watchpoint pinned the writer to `0x80069fcc` inside **`FUN_80069dbc`** — an LRU voice
   allocator that ages entries (`age += 1`) and calls `SpuSetNoiseVoice`. They increment because
   the looping **water sound** ages SPU voices. Unrelated to the visual.

2. **`0x8013ADDC` etc. → GPU primitive-buffer data, not a scroll.** Two values `0x34` apart
   ticked slowly (gated, ~+0.3/frame) — looked like a stride-`0x34` animated-texture table.
   Watchpoint pinned the writer to `0x80036230` inside **`FUN_80035ca4`** (a GTE textured-poly
   builder). The address is just primitive data in the **display-list buffer** (`~0x8013axxx`),
   rebuilt every frame; the "steady increment" was the camera moving a vertex coordinate. The
   nearby `scratchpad+0x80..0x90` writes are a **GTE rotation matrix** (`gte_rtir`/`gte_stIR1`),
   *not* a texture-V scroll (mis-read as `V = base + scroll` at first).

3. **`LoadImage` (`0x80079dc8`) is NOT called per-frame.** A breakpoint on it never fired during
   gameplay near water → animation is **not** VRAM-frame-upload based (the texture isn't swapped
   in VRAM each frame).

4. **Render-tree walk found no chokepoint.** Main per-frame loop `FUN_80014bd4` → `FUN_800422b8`
   (HUD/render) → `FUN_80040ae4` (object/sprite render, iterates the 200-object array) /
   `FUN_8003bfd0` (floor/world grid via `FUN_8003bb04` → `FUN_80035358`) → poly builders
   `FUN_8003e34c` / `FUN_8003f304` / `FUN_80035ca4`. UVs are computed inline through GTE; the
   counters touched are scattered and per-poly. No single "advance animated textures" call.

5. **VRAM diff** (`/api/v1/gpu/vram/raw`, 1024×512×16bpp): most change is the two display
   framebuffers (≈px 0–320, swapping each frame as the scene renders). A few small texture-area
   regions change (e.g. ≈px 960–1024, py 64–128) but couldn't be tied to a CPU-side lever
   (uploads are GPU DMA, invisible to CPU write-watchpoints).

**Tooling unlocked here (the lasting win):** PCSX-Redux **GDB** `Z2`/`Z4` data watchpoints do
**not** fire on this build, and the Web API exposes no breakpoint/Lua endpoint — but a
**PCSX-Redux Lua `PCSX.addBreakpoint(addr,'Write',width, name, invoker)`** with a *custom invoker*
works and, because a custom invoker overrides the default `pauseEmulator()`, it **logs the writer
PC without pausing the game**. `tools/redux_watchpoint.lua` arms such a watchpoint and dumps the
distinct writer PCs (+`ra`) to a file. This is the right tool for future hunts (it found both
dead-end writers above in seconds). A custom invoker that *restores* a captured value on each
write also gives a non-pausing **freeze** (to test "does X drive this animation?"). Note: very
hot addresses (written many times/frame, e.g. display-list buffers) can destabilize the emulator
under the callback — prefer watching cooler, object-level state, and wrap the callback in `pcall`.

## 9. Door animation investigation (mechanism mapped, fix deferred)

**Goal:** make doors open/close at the original speed at 60 fps (they currently snap ~4× fast).

**Mechanism.** Doors are handled by `FUN_80047010`, the dispatcher for **interactive world
objects** (doors, switches, elevators…) — a different array (`~0x80191a5c`) from enemies. It's
a **timed state machine** per object:

- A per-frame **state timer** `obj[0x38]` increments `+1` each frame (`obj[0x38] = uVar5 + 1`).
- Phases are keyed off that timer's value:
  - `timer < 0x20` (0–31): **opening** — rotation angle `obj[0x1e] += 0x20`/frame (`@0x800482fc`),
    so over 32 frames it reaches `0x400` (= 90°, fully open).
  - hold.
  - `timer ∈ [0x12c, 0x14c)` (300–331): **closing** — `obj[0x1e] -= 0x20`/frame (`@0x80048458`).
- `obj[0x1e]` is the door's **rotation angle**, consumed via `rcos/rsin((angle) - 0x400)` and
  `FUN_8001660c` (matrix) to swing the door geometry.
- There are **several door-type variants** (open ramps also at the equivalents of decompile
  lines 238/931, closes at 179/273/881), each with its own ramp + phase constants.

**Why a naive ÷4 fails.** Scaling only the ramp step (`0x20 → 0x08`) makes the door move smoothly
but the opening *phase* is still 32 frames (timer-gated), so it only covers ¼ of the 90° rotation
and stops part-open. (Verified live: with ±0x08 the door "opens a little bit.")

**Correct fix (deferred).** Stretch the whole sequence 4×, two consistent options:
1. **Gate the state-timer**: make `obj[0x38]` increment `+1` every 4th frame (cave/self-counter
   gate, like ATTACK/MAGIC) **and** ÷4 the ramps. Then the opening phase lasts 128 frames and the
   ÷4 ramp reaches `0x400` exactly at the phase boundary. One gate covers all door types — but the
   timer/handler is shared by *all* interactive objects (switches, elevators, moving platforms), so
   it scales those too (probably desirable at 60 fps, but verify nothing timing-critical breaks).
2. **Per-door-type phase extension**: ÷4 each ramp step **and** widen each phase window
   (`<0x20 → <0x80`, `[0x12c,0x14c) → [0x12c,0x1ac)`, …) so each door type opens/closes over 4× the
   frames. More edits, but scoped to doors only.

**How it was found (good template for timed world state):** triple-diff **closed → open →
auto-closed** isolated the door angle `obj[0x1e]` (the tested door's was `0x80193b72`: `0 → 960 →
0`); then `tools/redux_watchpoint.lua` on that address pinned the writer `0x80048300` →
`FUN_80047010`. The "changed-then-returned" filter cuts through the render/sound/timer noise that
a plain before/after diff drowns in.
