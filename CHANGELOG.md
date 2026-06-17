# Changelog

All notable changes to the King's Field II (USA) 60 FPS patcher. Format based on
[Keep a Changelog](https://keepachangelog.com/); the patcher reports its version on the CLI
(`--version`) and in the web UI, sourced from `VERSION` in `src/build_60fps_patch.py`.

## [Unreleased]
- **Mist constant-drain**: the poison-mist field now drains ÷4 (good) but in short steps with
  brief gaps rather than the stock continuous drain — acceptable but not yet exact (see RESEARCH §16).
- Player death animation and secret-door / key-use animation: under investigation.
- Projectile speed: **deferred** — pooled particle/effect system with no single position-mover
  to scale safely (see RESEARCH §15, §19).
- Steep-slope climb: **deferred** for binary patching (intertwined move resolution); one untried
  incline-reprojection hook identified for a future A/B test (see RESEARCH §17, §19).

## [1.5.0] — 2026-06-17 — Enemy melee damage
### Fixed
- **Enemies dealt ~4× damage at 60 fps.** The player take-a-hit resolver (`FUN_8002ab18`, which
  subtracts from HP `@0x801b24fc` and drives the red damage-flash) is invoked **once per frame**
  while an enemy sits in its attack-active animation window; the ÷4 animation slow-down stretches
  that (originally 1-frame) window across ~4 real frames, so the hit landed 4× (live-confirmed: one
  swing = 4 hits × 14 HP). The function entry is now redirected to a code cave that ÷N-gates it, so
  exactly **one** hit lands per swing (full per-hit damage preserved — not a lossy ¼-scale — so weak
  enemies still hurt), and the flash/knockback fire once per hit too. The fall-damage
  (`FUN_8002ed60`) and poison (`FUN_8002a6a0`) HP paths are separate and unaffected. (RESEARCH §18.)

## [1.4.0] — 2026-06-13 — Poison & damage-flash
### Fixed
- **Poison damage** ticked ~4× too fast at 60 fps. The status handler (`FUN_80031e9c`) sets the
  red screen damage-flash (`DAT_801b2658`), refreshes `DAT_801b265a`, and drains 1 HP every tick;
  the tick body is now redirected to a code cave that ÷N-gates the **flash and the drain together**,
  so poison drains at the original rate with **exactly one red blink per HP** (earlier drain-only
  gating left the flash firing every tick → "4 blinks per HP"). The poison **mist** field drains
  ÷4 slower as well and keeps its solid-red screen. (RESEARCH §16.)

## [1.3.0] — 2026-06-12 — Camera & head-bob
### Added
- `--bob on|off` (web: "Disable head-bob" checkbox). Default **on**.
### Fixed
- **Vertical look (pitch)** ran ~4× too fast — scaled the per-frame pitch advance ÷4 (÷2 in half mode).
- **Head-bob** now runs at the original speed (phase increment scaled ÷4) instead of being disabled;
  `--bob off` restores the old disabled behavior.

## [1.2.0] — 2026-06-11 — Web patcher
### Added
- **Browser patcher** (`docs/`, GitHub Pages, King's-Field-themed) — runs 100% client-side; your
  disc image never leaves your machine. Choose mode / widescreen cull / experimental FOV / `.bps`.
- **Single source of truth**: `tools/export_manifest.py` → `docs/patches.json` → `docs/engine.js`,
  guarded by a byte-parity test so the web and CLI patchers can never drift.
- **Dump verification**: shows the required dump (SLUS-00255) and its size/CRC32/MD5/SHA-1, and
  verifies the loaded file against all four (chunked hashing so the 571 MB file doesn't freeze the UI).
### Removed
- GitHub Actions CI pipeline (no longer needed).

## [1.1.0] — 2026-06-11 — Widescreen
### Added
- `--fov DEG` — customizable horizontal FOV via the GTE H register. **[experimental]**
- `--cull on|off` — widescreen edge-culling fix: widens the dungeon PVS cone so walls/objects/corners
  stop popping at the 16:9 edges. **[experimental]**
### Fixed
- Widescreen cull flicker (edge geometry / vanishing skybox): root-caused to the PVS cone crossing the
  `0x258` draw-distance limiter on camera pitch; kept the cone permanently in the cos-scaled regime.
### Notes
- Documented the inherent limits: ~6% shorter center draw distance, slight distant-tree edge wobble,
  and (at wide FOV) distant side-popping from KF2's forward-Z fog. See RESEARCH §13.

## [1.0.0] — 2026-06-09 — Core speed-compensation
Raise the hard 15 FPS cap to **60 FPS** (or 30) while scaling every per-frame system back to the
game's original speed, so it plays exactly like the original — just smoother. Portable: the cap is
fixed, so any sufficient emulator overclock gives the correct speed.
### Added
- Frame cap **15 → 60** (`quarter`, default) or **30** (`half`).
- Player **walk** and **turn** speed ÷N.
- Player **swing animation** ÷N (arc + hit-detection windows scaled together).
- **Enemy + NPC animation** ÷N (near **and** distant/LOD), and **enemy turning/facing** ÷4.
- **Doors** open/close at the correct speed (full rotation over 4× the frames).
- **Menus** capped at 60 FPS with deterministic cursor auto-repeat (taps stay instant).
- **Gravity / falling** rescaled to original speed (fall damage + terminal velocity preserved).
- **Animated sprites** (fire/flames) frame-cycling ÷N.
- **Water / scrolling textures** CLUT-scroll ÷N.
- **Notification messages** appear/hold/fade ÷N (readable again, not a flash).
- **Item pickup** display animations (move-in/spin/return) ÷N.
- **Magic stamina** gauge fill + refill delay ÷N (matches the attack bar).
- Tooling: portable Python patcher, synthetic-fixture test suite, and live RE helpers
  (PCSX-Redux + Ghidra). No copyrighted game data in the repo.
### Fixed
- **4× enemy drops**: dying enemies spawned all loot 4× at 60 FPS — gated the death-drop edge check
  (`DROPEDGE`) so it fires exactly once.
### Notes
- Head-bob shipped **disabled** here as a stopgap (it ran too fast); fixed properly in 1.3.0.

[Unreleased]: https://github.com/JonathanDC64/kf2-60fps/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.5.0
[1.3.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.3.0
[1.2.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.2.0
[1.1.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.1.0
[1.0.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.0.0
