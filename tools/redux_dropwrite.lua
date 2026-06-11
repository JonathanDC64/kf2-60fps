-- KF2 drop-write catcher (PCSX-Redux Lua, LuaJIT). NARROW watchpoints (these work).
-- The RAM diff found the loot array at base 0x80197754 (stride 0x44): the 4 gold +
-- 4 herb flipped slot bytes 0x80197758 and 0x80197ca8 from free->allocated. Watch
-- those exact bytes (width 1) and log the WRITER pc/ra -> the drop-creation site
-- inside FUN_80047010. Kill an enemy in a fresh area so a low slot is reused.
--
-- Run: dofile('C:/dev/projects/kf2-60fps/tools/redux_dropwrite.lua')
--      kf2dw_reset()   -- optional, right before the killing blow
--      (kill, wait for gold+herb), then report "done".

local WATCH = { 0x80197758, 0x8019775a, 0x80197ca8, 0x80197754 }  -- slot bytes that changed + base
local BEAT  = 0x80019614
local OUT   = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\dropwrite.txt]]

kf2dw_bps = kf2dw_bps or {}
for _, bp in ipairs(kf2dw_bps) do pcall(function() bp:remove() end) end
kf2dw_bps = {}
if kf2dwbeat then kf2dwbeat:remove(); kf2dwbeat = nil end

local sites = {}   -- "addr@pc" -> {addr=, pc=, ra=, count=}
local order = {}
local beats = 0

local function dump()
  local f = io.open(OUT, 'w'); if not f then return end
  f:write(string.format('# writers of loot array bytes (beats=%d)\n', beats))
  f:write('# watched: 80197758 8019775a 80197ca8 80197754\n')
  for _, k in ipairs(order) do
    local e = sites[k]
    f:write(string.format('  wrote %08x   pc=%08x  ra=%08x  count=%d\n', e.addr, e.pc, e.ra, e.count))
  end
  f:close()
end

function kf2dw_reset()
  sites = {}; order = {}; dump(); print('kf2dw reset (beats=' .. beats .. ')')
end

for _, addr in ipairs(WATCH) do
  local a = addr
  kf2dw_bps[#kf2dw_bps+1] = PCSX.addBreakpoint(a, 'Write', 1, 'kf2-dw', function()
    pcall(function()
      local r = PCSX.getRegisters()
      local key = string.format('%08x@%08x', a, r.pc)
      local e = sites[key]
      if e then e.count = e.count + 1
      else
        sites[key] = { addr = a, pc = r.pc, ra = r.GPR.n.ra, count = 1 }
        order[#order+1] = key
      end
    end)
  end)
end

kf2dwbeat = PCSX.addBreakpoint(BEAT, 'Exec', 4, 'kf2-dwbeat', function()
  pcall(function() beats = beats + 1; if beats % 30 == 0 then dump() end end)
end)

print('KF2 drop-write catcher armed on loot-array bytes -> ' .. OUT)
