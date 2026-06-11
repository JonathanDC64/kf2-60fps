-- KF2 value-freeze (PCSX-Redux Lua / LuaJIT 5.1 -- no &,|,<<,>> operators).
-- Holds a target address at a constant value WITHOUT pausing the emulator, by
-- restoring captured bytes on every write (custom invoker overrides the pause).
-- Use to test "does THIS counter drive that animation?": freeze it, look at the
-- screen -- if the animation stops, the counter drives it.
--
-- Run:  dofile([[C:\dev\projects\kingsfield2-recomp\KF2Recomp\kf2_freeze.lua]])
-- Stop: kf2fz:remove()

local ADDR  = 0x801aeb20   -- candidate texture-animation phase (cycles 0..31)
local WIDTH = 4            -- bytes

if kf2fz then kf2fz:remove(); kf2fz = nil end

local mem = PCSX.getMemPtr()
local off = ADDR % 0x200000                 -- RAM offset (no bit-mask needed)
-- capture the bytes to hold (byte-wise -> no shifts/bitops)
local b0, b1, b2, b3 = mem[off], mem[off+1], mem[off+2], mem[off+3]

kf2fz = PCSX.addBreakpoint(ADDR, 'Write', WIDTH, 'kf2-freeze', function()
  pcall(function()
    mem[off]   = b0
    mem[off+1] = b1
    mem[off+2] = b2
    mem[off+3] = b3
  end)
  -- no pauseEmulator() -> game keeps running, value stays frozen
end)

print(string.format('KF2 FREEZE armed on 0x%08x (held). kf2fz:remove() to release.', ADDR))
