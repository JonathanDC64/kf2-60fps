-- Memory write-watchpoint for PCSX-Redux (run in the Lua console / editor).
--
-- PCSX-Redux's GDB bridge does NOT implement data watchpoints (Z2/Z4 never fire),
-- but the native Lua API does. This arms a WRITE breakpoint whose *custom invoker*
-- overrides the default pause, so it logs the distinct instruction PCs that write a
-- target address WITHOUT freezing the emulator. Results -> a text file you can read.
--
-- Usage: set ADDR/WIDTH/OUT below, then in PCSX-Redux:
--   Debug -> Show Lua Console, and run:
--     loadfile([[<path>\redux_watchpoint.lua]])()
-- Play for a few seconds so the address gets written; read OUT for "pc  ra  hits".
--
-- Tip: a custom invoker that *restores* a captured value instead of logging gives a
-- non-pausing FREEZE (to test whether an address drives some animation/effect).
-- Caveat: extremely hot addresses (written many times per frame, e.g. display-list
-- buffers) can destabilize the emulator under the callback -- watch object-level state.

local ADDR  = 0x80000000   -- <-- address to watch
local WIDTH = 2            -- bytes (1/2/4)
local MAXPC = 16           -- stop after this many distinct writer PCs
local OUT   = [[wp_hit.txt]]   -- <-- absolute path recommended

if _G.kf2bp then _G.kf2bp:remove(); _G.kf2bp = nil end   -- clear any previous arm

local seen, order, ndistinct = {}, {}, 0

local function dump()
  local f = io.open(OUT, 'w'); if not f then return end
  f:write(string.format('# writers of 0x%08x (width %d)\n', ADDR, WIDTH))
  for _, pc in ipairs(order) do
    local e = seen[pc]
    f:write(string.format('%08x  ra=%08x  hits=%d\n', pc, e.ra, e.hits))
  end
  f:close()
end

_G.kf2bp = PCSX.addBreakpoint(ADDR, 'Write', WIDTH, 'redux-wp', function()
  local ok, r = pcall(PCSX.getRegisters)
  if not ok then return end
  local pc, e = r.pc, seen[r.pc]
  if e then
    e.hits = e.hits + 1
  else
    seen[pc] = { ra = r.GPR.n.ra, hits = 1 }
    order[#order + 1] = pc
    ndistinct = ndistinct + 1
    pcall(dump)
    if ndistinct >= MAXPC then _G.kf2bp:disable() end
  end
  -- no pauseEmulator() -> keeps running (custom invoker overrides default pause)
end)

print(string.format('redux watchpoint armed on 0x%08x (Write,%d) -> %s', ADDR, WIDTH, OUT))
