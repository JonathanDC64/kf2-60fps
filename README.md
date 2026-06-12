# King's Field II (USA) — 60 FPS Patch

A patcher that makes **King's Field II (USA, SLUS-00255)** run at a smooth **60 FPS**
while keeping the game playing at its original speed.

The original game runs its logic once per rendered frame and is hard-capped at ~15 FPS.
If you simply uncap it (e.g. via emulator overclock), everything runs ~4× too fast. This
patch raises the cap to 60 FPS **and** scales each per-frame system back down so the game
feels like the original — just smoother. It's **portable**: because the cap is fixed at
60 FPS, any sufficient overclock value gives the correct speed (it can't run faster than
the cap).

> ⚠️ **No game data is included.** This repo contains only patch scripts, tools, and
> research. You must supply your own legally-obtained dump of your King's Field II disc.

## What it fixes

| System | Patched behavior |
| --- | --- |
| Frame cap | 15 FPS → **60 FPS** (`quarter`) or 30 FPS (`half`) |
| Player walk / turn | scaled ÷4 (÷2 in half mode) |
| Head-bob | disabled (cosmetic; ran too fast) |
| Enemy movement | ÷4, with rounding so slow/diagonal enemies aren't starved |
| Attack bar (weapon charge) | recharges ÷4 (correct attack cadence) |
| Magic stamina gauge | fills ÷4, and its refill **delay** matches the attack bar |
| Player swing animation | ÷4 (arc speed + hit-detection windows scaled together) |
| Enemy + NPC animation | ÷4 (near **and** distant enemies + NPCs; walk/idle/attack) |
| Enemy turning | ÷4 facing-slew (still faces you, just turns at the right speed) |
| Doors | open/close at the correct speed (full rotation over 4× the frames) |
| Menus (inventory/shops) | capped at 60 FPS and cursor auto-repeat held at the right speed (taps stay instant) |
| Gravity / falling | falls at the original speed (N² integration rescaled; fall damage preserved) |
| Animated sprites (fire/flames) | texture-frame cycling ÷4 (billboard flames animate at the right speed) |
| Water / scrolling textures | CLUT scroll ÷4 (water shimmer animates at the right speed) |
| Notification messages | appear/hold/fade ÷4 (bottom-screen text stays readable, not a flash) |
| Item pickup | move-in/spin/fast-spin/return ÷4 (the pickup display plays at the right speed) |

Optional/cosmetic only: a non-cosmetic head-bob (currently disabled). See
[docs/RESEARCH.md](docs/RESEARCH.md) for the full reverse-engineering write-up.

## Web patcher (no install)

A browser version lives in [`docs/`](docs/) and runs **entirely client-side** — your disc image
never leaves your machine. Enable GitHub Pages (Settings → Pages → *Deploy from a branch* →
`main` / `/docs`) to host it; then load your `.bin`, pick the options (60/30 fps, widescreen
culling, experimental FOV), and download the patched `.bin` + `.cue` (and optionally a `.bps`).

It shares a **single source of truth** with the Python patcher: `tools/export_manifest.py` exports
the patch data to [`docs/patches.json`](docs/patches.json), and `docs/engine.js` applies it. A
parity test (`tests/test_web_parity.py`) asserts the web engine produces **byte-identical** output
to the Python patcher, so the two never drift. **After changing any patch, run
`python tools/export_manifest.py`** (the test will remind you if you forget).

## Quick start (CLI)

Requires Python 3.8+ and your own `King's Field II (USA).bin` (raw `MODE2/2352` dump,
571,766,496 bytes, CRC32 `F8A4C585`).

```sh
python src/build_60fps_patch.py "King's Field II (USA).bin" "King's Field II [60fps].bin"
```

Then load the patched `.bin`/`.cue` in DuckStation with CPU overclock high enough to hold
60 FPS (≈160 %+; more is fine — the cap keeps the speed correct).

Options:

```
--mode quarter|half   quarter = 60 fps + 1/4 speed (default); half = 30 fps + 1/2 speed
--cull on|off         [EXPERIMENTAL] widescreen edge-culling fix: widen the dungeon's visible-cell
                      cone so walls, objects and the bottom corners stop popping at the 16:9 edges.
                      Use with DuckStation's widescreen rendering. Default: on when --fov is set,
                      else off. KF2's fixed 25×25 visibility grid cos-scales a widened cone, so the
                      center draw distance is ~6% shorter than stock (the price of a stable wide cone).
--fov DEG             [EXPERIMENTAL] custom horizontal FOV in degrees (stock ~77; e.g. 90/100).
                      Known issue: at a wide FOV, distant geometry at the far left/right can't be
                      fully fogged (KF2's fog is forward-Z based) and may pop. For clean widescreen,
                      prefer the stock FOV with --cull on.
--bps patch.bps       also write a shareable BPS patch (contains only our edits, no game code)
--no-crc-check        skip the source size/CRC verification
```

For 16:9 widescreen, build with `--cull on` and enable DuckStation's widescreen rendering (16:9).
See [docs/RESEARCH.md](docs/RESEARCH.md) §13 for the FOV/fog/culling reverse-engineering details.

### Sharing a patch

A patched 571 MB `.bin` can't be shared (it's the copyrighted game). A **BPS patch**
can — it contains only this project's modifications. Generate one with `--bps`, and
others apply it to their own dump with a BPS tool such as
[Floating IPS](https://www.romhacking.net/utilities/1040/) or `beat`.

## Tools

`tools/` holds the live reverse-engineering helpers used to find and validate the patches
against [PCSX-Redux](https://github.com/grumpycoders/pcsx-redux) (deterministic
frame-stepping, memory capture, code caves) and Ghidra. See [docs/USAGE.md](docs/USAGE.md).

## License

MIT — see [LICENSE](LICENSE). This applies to the scripts, tools, and documentation only;
it grants no rights to King's Field II, which is © FromSoftware.
