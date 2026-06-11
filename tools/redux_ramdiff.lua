-- KF2 RAM differ (PCSX-Redux Lua, LuaJIT). READ-ONLY, no breakpoints.
-- Finds where the gold/herb drop is stored by snapshotting a broad RAM window
-- before the kill and diffing after. A freshly allocated object flips its slot's
-- "free" marker (0xff) to a type, so 0xff->non-0xff transitions cluster exactly
-- at the loot array -> reveals its base + stride.
--
-- Usage in the PCSX-Redux Lua console:
--   dofile('C:/dev/projects/kf2-60fps/tools/redux_ramdiff.lua')   -- loads helpers
--   kf2snap()        -- call standing next to the live enemy, BEFORE the kill
--   (kill the enemy, wait until gold + herbs are on the floor)
--   kf2diff()        -- writes ram_diff.txt, prints summary
--
-- Re-run kf2snap()/kf2diff() as many times as needed; dofile only once.

local LO  = 0x80196000
local HI  = 0x80199000           -- focused: the stride-0x44 loot array region (~0x80197754)
local OUT = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\ram_diff.txt]]

local ffi = require('ffi')
local mem = PCSX.getMemPtr()
local span = HI - LO
local base_off = bit.band(LO, 0x1fffff)

function kf2snap()
  kf2snapshot = ffi.string(mem + base_off, span)   -- byte-exact copy
  print(string.format('kf2snap: captured [%08x,%08x) = %d bytes', LO, HI, span))
end

function kf2diff()
  if not kf2snapshot then print('call kf2snap() first'); return end
  local snap = kf2snapshot
  local f = io.open(OUT, 'w')
  f:write(string.format('# RAM diff [%08x,%08x)\n', LO, HI))

  -- (1) 0xff -> non-0xff transitions (slot allocations) -- the key signal
  f:write('# --- allocations (byte 0xff -> non-0xff) ---\n')
  local allocs = {}
  for i = 0, span - 1 do
    local old = snap:byte(i + 1)
    if old == 0xff then
      local new = mem[base_off + i]
      if new ~= 0xff then
        allocs[#allocs + 1] = LO + i
      end
    end
  end
  for _, a in ipairs(allocs) do
    f:write(string.format('  %08x  ->0x%02x\n', a, mem[bit.band(a,0x1fffff)]))
  end
  f:write(string.format('# alloc transitions = %d\n', #allocs))

  -- (2) infer stride from consecutive alloc gaps (helps identify the array)
  if #allocs > 1 then
    f:write('# gaps between consecutive alloc addresses:\n')
    for k = 2, #allocs do
      f:write(string.format('  +0x%x\n', allocs[k] - allocs[k-1]))
    end
  end
  f:close()
  print(string.format('kf2diff: %d alloc transitions -> %s', #allocs, OUT))
end

print('kf2 ramdiff loaded. Call kf2snap() before the kill, kf2diff() after gold appears.')
