# Usage

## Patching your game

1. Dump your King's Field II (USA) disc to a raw `MODE2/2352` `.bin` + `.cue`
   (e.g. with [Redump](http://redump.org/)-style tooling). Expected:
   571,766,496 bytes, CRC32 `F8A4C585`.
2. Run the patcher:
   ```sh
   python src/build_60fps_patch.py "King's Field II (USA).bin" "King's Field II [60fps].bin"
   ```
   It prints each patch site it edits, and warns (but continues) if your dump's
   size/CRC doesn't match the reference.
3. Make a `.cue` for the output (copy your original `.cue` and change the `FILE` name):
   ```
   FILE "King's Field II [60fps].bin" BINARY
     TRACK 01 MODE2/2352
       INDEX 01 00:00:00
   ```
4. Load it in **DuckStation** and set **CPU overclock** high enough to render a stable
   60 FPS (≈160 %+ depending on scene; higher is fine — the 60 FPS cap keeps speed
   correct). Without overclock the game renders below 60 and will feel slow.

### Modes
- `--mode quarter` (default): 60 FPS cap + 1/4 per-frame scaling.
- `--mode half`: 30 FPS cap + 1/2 scaling (less overclock needed).

### Sharing a patch
```sh
python src/build_60fps_patch.py input.bin out.bin --bps kf2_60fps.bps
```
`kf2_60fps.bps` contains only this project's edits (a couple hundred bytes) and is safe to
share. Apply it to a clean dump with [Floating IPS](https://www.romhacking.net/utilities/1040/)
(`Apply BPS Patch`) or `beat`. (Prefer xdelta3? `xdelta3 -e -s input.bin out.bin out.xdelta`.)

## Reverse-engineering tools (`tools/`)

These were used to find and validate the patches. They talk to a running
[PCSX-Redux](https://github.com/grumpycoders/pcsx-redux) with its **Web Server**
(`:8080`) and **GDB Server** (`:3333`) enabled and the **interpreter** (not the
dynarec) selected, with the game running.

- **`redux_framestep.py <steps> [poke=ADDR:HEXBYTES] <addr:size> ...`** — deterministic
  per-frame sampling. Breakpoints the once-per-frame sync function and reads the given
  addresses each frame. `poke=` writes a value once inside the paused loop (e.g. to drain
  a gauge and measure its refill rate). The frame-sync breakpoint address is at the top of
  the script (`FRAME_BP`) — set it for your build.
- **`redux_framewatch.py <base> <length> <steps>`** — frame-steps and reports which 2-byte
  fields in a struct change per frame (finds animation/timer counters).
- **`redux_pokew.py <addr> <word> [...]`** — write 32-bit words to RAM (live patch tests).
- **`redux_watchpoint.py <addr> <len>`** — GDB write-watchpoint (note: unreliable on some
  PCSX-Redux builds; frame-stepping is the fallback).
- **`redux_ramdiff.py`** — diff two full-RAM snapshots to spot moving/animating values.

> If a script is killed mid-run it can leave the emulator **paused**; resume with
> `curl -X POST "http://localhost:8080/api/v1/execution-flow?function=resume"`.

### Ghidra scripts (`tools/ghidra/`)
Headless usage (after importing GAME.EXE into a project, e.g. with the PsyQ loader):
```sh
analyzeHeadless <proj_dir> <proj> -process GAME.EXE -noanalysis \
  -scriptPath tools/ghidra -postScript find_xref.java 0x801b2506
```
- **`find_xref.java <addr>`** — list every reference to a data address and decompile the
  referencing functions (output `ghidra_xref.txt` in the working dir).
- **`dump_one.java <addr>`** — decompile the function containing an address.
- **`dump_disasm.java <start> <end>`** — disassemble an address range.
