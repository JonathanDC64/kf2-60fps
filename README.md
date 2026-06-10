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
| Enemy + NPC animation | ÷4 (near enemies + NPCs; walk/idle/attack) |

Still in progress: distant (LOD) enemy animation, water/scrolling-texture animation, menu
speed, doors/world animations, and vertical (gravity) physics. See
[docs/RESEARCH.md](docs/RESEARCH.md).

## Quick start

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
--bps patch.bps       also write a shareable BPS patch (contains only our edits, no game code)
--no-crc-check        skip the source size/CRC verification
```

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
