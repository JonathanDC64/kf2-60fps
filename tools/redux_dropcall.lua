-- KF2 drop-call logger (PCSX-Redux Lua, LuaJIT). Exec hook on the drop spawner
-- FUN_800460bc @ 0x800460bc. Logs every call with the killed enemy's animation
-- state so we can see WHY it fires 4x. enemy ptr = a2 - 0x2c (a2 = &enemy[0x2c]).
-- Fields: [0x18]=anim timer, [0x66]=last step, [0x70]=substate, [0xe]=state byte.
--
-- Run: dofile('C:/dev/projects/kf2-60fps/tools/redux_dropcall.lua')
--      kf2dc_reset()   -- right before the killing blow
--      (kill, wait for drops), then "done".

local DROP = 0x800460bc
local BEAT = 0x80019614
local OUT  = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\dropcall.txt]]

if kf2dc   then kf2dc:remove();   kf2dc   = nil end
if kf2dcb  then kf2dcb:remove();  kf2dcb  = nil end

local mem = PCSX.getMemPtr()
local function rd8(a)  return mem[bit.band(a,0x1fffff)] end
local function rd16(a) return rd8(a) + rd8(a+1)*256 end

local log = {}
local beats = 0

local function dump()
  local f = io.open(OUT, 'w'); if not f then return end
  f:write(string.format('# FUN_800460bc drop calls (beats=%d, count=%d)\n', beats, #log))
  f:write('#  a0(kind) a1(item) enemy     timer  step  sub  state  ra\n')
  for _, e in ipairs(log) do f:write('  ' .. e .. '\n') end
  f:close()
end

function kf2dc_reset() log = {}; beats = 0; dump(); print('kf2dc reset') end

kf2dc = PCSX.addBreakpoint(DROP, 'Exec', 4, 'kf2-dc', function()
  pcall(function()
    local r = PCSX.getRegisters()
    local enemy = r.GPR.n.a2 - 0x2c
    log[#log+1] = string.format('a0=%d a1=0x%02x enemy=%08x timer=%04x step=%04x sub=%d state=0x%02x ra=%08x',
      bit.band(r.GPR.n.a0,0xff), bit.band(r.GPR.n.a1,0xff), enemy,
      rd16(enemy+0x18), rd16(enemy+0x66), rd16(enemy+0x70), rd8(enemy+0xe), r.GPR.n.ra)
    if #log <= 64 then dump() end
  end)
end)

kf2dcb = PCSX.addBreakpoint(BEAT, 'Exec', 4, 'kf2-dcb', function()
  pcall(function() beats = beats + 1; if beats % 30 == 0 then dump() end end)
end)

print('KF2 drop-call logger armed on FUN_800460bc -> ' .. OUT)
