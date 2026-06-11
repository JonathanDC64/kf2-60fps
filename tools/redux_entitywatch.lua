-- KF2 entity-array write tracer (PCSX-Redux Lua, LuaJIT).
-- The 4x gold drop is written directly into the entity array (no spawner call),
-- so this puts a RANGE Write-watchpoint over the whole array and records the
-- distinct WRITER instruction PCs (+ ra). The gold-creation instruction shows up
-- as a new PC right at the kill -> decompile that PC's function = the loot code.
--
-- Safe by construction: memory-only logging, file flush only on the frame hook
-- (~1/sec), and a hard cap on total callbacks (anti-crash).
--
-- Run: PCSX-Redux -> Debug -> Show Lua console:
--   dofile('C:/dev/projects/kf2-60fps/tools/redux_entitywatch.lua')
-- Then approach enemy, type  kf2ew_reset()  right before the killing blow,
-- land the blow, wait for the gold piles, stop, and report "done".

local ARR_BASE = 0x80185da8   -- entity/enemy array base
local ARR_SIZE = 200 * 0x88   -- 200 slots x 0x88 = 0x4400
local BEAT     = 0x80019614    -- frame pacer (throttled flush)
local HITCAP   = 20000         -- stop logging after this many writes (anti-runaway)
local OUT      = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\ew_hit.txt]]

if kf2ew  then kf2ew:remove();  kf2ew  = nil end
if kf2ewb then kf2ewb:remove(); kf2ewb = nil end

local sites = {}    -- pc -> {ra=, count=, firstbeat=, slot=, off=}
local order = {}    -- discovery order of distinct PCs
local beats = 0
local total = 0
local capped = false

local function dump()
  local f = io.open(OUT, 'w')
  if not f then return end
  f:write(string.format('# entity-array [%08x,+%x) writers   beats=%d total=%d%s\n',
          ARR_BASE, ARR_SIZE, beats, total, capped and '  (CAP HIT)' or ''))
  f:write('# pc        ra        count   slot  off   firstbeat\n')
  for _, pc in ipairs(order) do
    local e = sites[pc]
    f:write(string.format('  %08x  %08x  %6d  %4s  %4s  %d\n',
            pc, e.ra, e.count,
            e.slot and tostring(e.slot) or '?',
            e.off and string.format('0x%x', e.off) or '?',
            e.firstbeat))
  end
  f:close()
end

function kf2ew_reset()
  sites = {}; order = {}; total = 0; capped = false
  dump(); print('kf2ew reset (beats=' .. beats .. ')')
end

-- Write-breakpoint callback. PCSX-Redux passes the triggering address as arg1.
kf2ew = PCSX.addBreakpoint(ARR_BASE, 'Write', ARR_SIZE, 'kf2-ew', function(addr)
  if capped then return end
  pcall(function()
    total = total + 1
    if total >= HITCAP then capped = true; kf2ew:disable() end
    local r = PCSX.getRegisters()
    local pc = r.pc
    local e = sites[pc]
    if e then
      e.count = e.count + 1
    else
      local off, slot
      if addr then
        local rel = addr - ARR_BASE
        slot = math.floor(rel / 0x88)
        off  = rel % 0x88
      end
      sites[pc] = { ra = r.GPR.n.ra, count = 1, firstbeat = beats, slot = slot, off = off }
      order[#order + 1] = pc
    end
  end)
end)

kf2ewb = PCSX.addBreakpoint(BEAT, 'Exec', 4, 'kf2-ewbeat', function()
  pcall(function()
    beats = beats + 1
    if beats % 30 == 0 then dump() end
  end)
end)

print(string.format('KF2 entity-watch armed on [%08x,+%x) -> %s', ARR_BASE, ARR_SIZE, OUT))
print('Call kf2ew_reset() right before the killing blow to isolate the kill.')
