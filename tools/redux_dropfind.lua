-- KF2 drop-spawn finder (PCSX-Redux Lua).
-- Hooks the dynamic-object ALLOCATOR (FUN_8004b524 @ 0x8004b524) and the
-- category-spawn primitive (FUN_8004f414 @ 0x8004f414) at their entry, WITHOUT
-- pausing, and logs a histogram of return addresses (ra = the call site) plus,
-- for FUN_8004f414, the category arg a0. The 4x gold drop should appear here as
-- a burst of ~4 allocations sharing one ra -> that ra is the loot-spawn site.
--
-- Run: PCSX-Redux -> Debug -> Show Lua console -> paste this file -> Execute.
-- Then: load a save just before an enemy, land ONE killing blow, stop.
-- Results -> drop_hit.txt  (per-site: ra, count, sample a0).
--
-- Tip: type  kf2drop_reset()  in the console right before the killing swing to
-- zero the counts so only the kill's spawns are recorded.

local ALLOC = 0x8004b524   -- FUN_8004b524: free-slot allocator (pool @0x8018c298, 10x0x88)
local SPAWN = 0x8004f414   -- FUN_8004f414: category spawn primitive (a0 = category)
local PICK  = 0x80053c84   -- FUN_80053c84: universal PICKUP/effect spawner (gold/herb drops go here)
local AB18  = 0x8002ab18   -- FUN_8002ab18: universal projectile/effect/object spawner
local DMG   = 0x8004c668   -- FUN_8004c668: apply damage (a0 = enemy index)
local DEATH = 0x8004c0b0   -- FUN_8004c0b0: death/state transition (a0 = enemy ptr, a1 = action)
local BEAT  = 0x80019614   -- FUN_80019614: frame pacer (fires every frame) -- exec-bp sanity check
local OUT   = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\drop_hit.txt]]

if kf2alloc then kf2alloc:remove(); kf2alloc = nil end
if kf2spawn then kf2spawn:remove(); kf2spawn = nil end
if kf2beat  then kf2beat:remove();  kf2beat  = nil end
if kf2dmg   then kf2dmg:remove();   kf2dmg   = nil end
if kf2death then kf2death:remove(); kf2death = nil end
if kf2ab18  then kf2ab18:remove();  kf2ab18  = nil end
if kf2pick  then kf2pick:remove();  kf2pick  = nil end

local alloc_sites = {}   -- ra -> count           (FUN_8004b524 callers)
local spawn_sites = {}   -- ra -> {count=, a0=}   (FUN_8004f414 callers + category)
local ab18_sites = {}    -- ra -> count           (FUN_8002ab18 callers)
local pick_sites = {}    -- ra -> {count=, t=}    (FUN_80053c84 callers + type a2)
local seq = {}           -- ordered event log (to see the burst)
local beats = 0          -- frame-pacer hit count (proves Exec breakpoints fire)

local function dump()
  local f = io.open(OUT, 'w')
  if not f then return end
  f:write(string.format('# heartbeat (FUN_80019614 frame-pacer) hits = %d  <- if 0, Exec bps are NOT firing\n', beats))
  f:write('# FUN_8004b524 allocator call sites (ra -> count)\n')
  for ra, n in pairs(alloc_sites) do
    f:write(string.format('  alloc  ra=%08x  count=%d\n', ra, n))
  end
  f:write('# FUN_8004f414 spawn call sites (ra -> count, last category a0)\n')
  for ra, e in pairs(spawn_sites) do
    f:write(string.format('  spawn  ra=%08x  count=%d  a0=0x%x\n', ra, e.count, e.a0))
  end
  f:write('# FUN_8002ab18 spawner call sites (ra -> count)\n')
  for ra, n in pairs(ab18_sites) do
    f:write(string.format('  ab18   ra=%08x  count=%d\n', ra, n))
  end
  f:write('# FUN_80053c84 PICKUP-spawner call sites (ra -> count, last type a2)  <-- gold/herb here\n')
  for ra, e in pairs(pick_sites) do
    f:write(string.format('  pick   ra=%08x  count=%d  type=0x%x\n', ra, e.count, e.t))
  end
  f:write('# event sequence (most recent 60)  [dmg=damage(a0=enemy), death=transition(a0=enemy,a1=action)]\n')
  local start = math.max(1, #seq - 59)
  for i = start, #seq do f:write('  ' .. seq[i] .. '\n') end
  f:close()
end

function kf2drop_reset()
  alloc_sites = {}; spawn_sites = {}; ab18_sites = {}; pick_sites = {}; seq = {}; beats = 0
  dump()
  print('kf2drop counts reset')
end

local function push(s)   -- in-memory only; the heartbeat flushes to disk ~1/sec
  seq[#seq + 1] = s
  if #seq > 200 then table.remove(seq, 1) end
end

kf2dmg = PCSX.addBreakpoint(DMG, 'Exec', 4, 'kf2-dmg', function()
  pcall(function()
    local r = PCSX.getRegisters()
    push(string.format('dmg    enemy=%d  ra=%08x', bit.band(r.GPR.n.a0, 0xffff), r.GPR.n.ra))
  end)
end)

kf2death = PCSX.addBreakpoint(DEATH, 'Exec', 4, 'kf2-death', function()
  pcall(function()
    local r = PCSX.getRegisters()
    push(string.format('death  enemy=%08x  action=%d  ra=%08x', r.GPR.n.a0, bit.band(r.GPR.n.a1, 0xff), r.GPR.n.ra))
  end)
end)

kf2ab18 = PCSX.addBreakpoint(AB18, 'Exec', 4, 'kf2-ab18', function()
  pcall(function()
    local r = PCSX.getRegisters()
    local ra = r.GPR.n.ra
    ab18_sites[ra] = (ab18_sites[ra] or 0) + 1
    push(string.format('ab18   ra=%08x  a0=0x%x', ra, r.GPR.n.a0))
  end)
end)

kf2pick = PCSX.addBreakpoint(PICK, 'Exec', 4, 'kf2-pick', function()
  pcall(function()
    local r = PCSX.getRegisters()
    local ra = r.GPR.n.ra
    local t  = r.GPR.n.a2
    local e = pick_sites[ra] or { count = 0, t = 0 }
    e.count = e.count + 1; e.t = t
    pick_sites[ra] = e
    push(string.format('pick   ra=%08x  type=0x%x', ra, t))
  end)
end)

kf2beat = PCSX.addBreakpoint(BEAT, 'Exec', 4, 'kf2-beat', function()
  pcall(function()
    beats = beats + 1
    if beats % 30 == 0 then dump() end   -- dump ~once/sec, avoid per-frame file churn
  end)
end)

kf2alloc = PCSX.addBreakpoint(ALLOC, 'Exec', 4, 'kf2-alloc', function()
  pcall(function()
    local ra = PCSX.getRegisters().GPR.n.ra
    alloc_sites[ra] = (alloc_sites[ra] or 0) + 1
    push(string.format('alloc  ra=%08x', ra))
  end)
end)

kf2spawn = PCSX.addBreakpoint(SPAWN, 'Exec', 4, 'kf2-spawn', function()
  pcall(function()
    local r = PCSX.getRegisters()
    local ra = r.GPR.n.ra
    local a0 = r.GPR.n.a0
    local e = spawn_sites[ra] or { count = 0, a0 = 0 }
    e.count = e.count + 1; e.a0 = a0
    spawn_sites[ra] = e
    push(string.format('spawn  ra=%08x  a0=0x%x', ra, a0))
  end)
end)

print('KF2 drop-finder armed: beat@' .. string.format('%08x', BEAT)
      .. ' alloc@' .. string.format('%08x', ALLOC)
      .. ' spawn@' .. string.format('%08x', SPAWN) .. ' -> ' .. OUT)
print('Call kf2drop_reset() right before the killing blow to isolate the kill.')
