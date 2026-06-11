-- KF2 memory-write watchpoint (PCSX-Redux Lua).
-- Logs the distinct instruction PCs that WRITE a target address, WITHOUT pausing
-- the emulator (custom invoker overrides the default pause), to a file the
-- automation can read. Change ADDR/WIDTH, then run this in the Lua console.
--
-- Run: open PCSX-Redux -> Debug -> "Show Lua console" (or the Lua editor),
-- paste this whole file, press Enter / Execute. Then play for a few seconds.
-- Results -> wp_hit.txt (distinct "pc ra hits").

local ADDR  = 0x801929a6   -- item-pickup spin rotation angle (climbs steadily, wraps) -- find writer
local WIDTH = 2            -- bytes
local MAXPC = 16           -- stop after this many distinct writer PCs
local OUT   = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\wp_hit.txt]]

if kf2bp then kf2bp:remove(); kf2bp = nil end   -- clear any previous arm

local seen = {}       -- pc -> {ra=, hits=}
local order = {}      -- insertion order of distinct pcs
local ndistinct = 0

local function dump()
  local f = io.open(OUT, 'w')
  if not f then return end
  f:write(string.format('# writers of 0x%08x (width %d)\n', ADDR, WIDTH))
  for _, pc in ipairs(order) do
    local e = seen[pc]
    f:write(string.format('%08x  ra=%08x  hits=%d\n', pc, e.ra, e.hits))
  end
  f:close()
end

kf2bp = PCSX.addBreakpoint(ADDR, 'Write', WIDTH, 'kf2-door', function()
  pcall(function()
    local r = PCSX.getRegisters()
    local pc = r.pc
    local e = seen[pc]
    if e then
      e.hits = e.hits + 1
    else
      seen[pc] = { ra = r.GPR.n.ra, hits = 1 }
      order[#order + 1] = pc
      ndistinct = ndistinct + 1
      dump()
      if ndistinct >= MAXPC then
        kf2bp:disable()
      end
    end
    total = (total or 0) + 1
    if total >= 120 then kf2bp:disable() end   -- hard cap: stop after 120 hits (anti-crash)
  end)
  -- no pauseEmulator() -> emulator keeps running (custom invoker overrides pause)
end)

print(string.format('KF2 watchpoint armed on 0x%08x (Write,%d) -> %s', ADDR, WIDTH, OUT))
