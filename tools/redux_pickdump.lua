-- KF2 entity-array dumper (PCSX-Redux Lua, LuaJIT). READ-ONLY, no breakpoints.
-- Dumps active slots of the candidate world-object arrays so we can locate the
-- gold/herb ground drops. Free slot = byte[0]==0xff. Run AFTER a kill once the
-- piles are on the floor; match the 24/5/13-style amounts you scanned earlier.
--
-- Run: dofile('C:/dev/projects/kf2-60fps/tools/redux_pickdump.lua')

local ARRAYS = {
  { name = 'entity',  base = 0x80185da8, stride = 0x88, count = 200, show = 0x30 },
  { name = 'dynpool', base = 0x8018c298, stride = 0x88, count = 10,  show = 0x30 },
  { name = 'effects', base = 0x801b80ec, stride = 0x4c, count = 128, show = 0x2c },
}
local OUT = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\pick_dump.txt]]

local mem = PCSX.getMemPtr()
local function rd8(addr) return mem[bit.band(addr, 0x1fffff)] end

local f = io.open(OUT, 'w')
for _, A in ipairs(ARRAYS) do
  local active = 0
  f:write(string.format('==== %s [%08x] stride=0x%x count=%d ====\n', A.name, A.base, A.stride, A.count))
  f:write('# slot  addr      <bytes 0..0x' .. string.format('%x', A.show-1) .. '>\n')
  for i = 0, A.count-1 do
    local a = A.base + i*A.stride
    if rd8(a) ~= 0xff then
      active = active + 1
      local parts = {}
      for o = 0, A.show-1 do parts[#parts+1] = string.format('%02x', rd8(a+o)) end
      f:write(string.format('  %3d  %08x  %s\n', i, a, table.concat(parts, ' ')))
    end
  end
  f:write(string.format('# %s active = %d\n\n', A.name, active))
end
f:close()
print('KF2 entity dump -> ' .. OUT)
