# Changelog

All notable changes to the King's Field II (USA) 60 FPS patcher. Format based on
[Keep a Changelog](https://keepachangelog.com/); the patcher reports its version on the CLI
(`--version`) and in the web UI, sourced from `VERSION` in `src/build_60fps_patch.py`.

## [Unreleased]
- Projectile speed, poison-damage tick, player death animation, secret-door / key-use
  animation, and enemy hit-flash: under investigation (need live PCSX-Redux probing).

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

[Unreleased]: https://github.com/JonathanDC64/kf2-60fps/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.3.0
[1.2.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.2.0
[1.1.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.1.0
[1.0.0]: https://github.com/JonathanDC64/kf2-60fps/releases/tag/v1.0.0
