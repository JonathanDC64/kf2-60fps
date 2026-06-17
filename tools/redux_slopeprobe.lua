-- redux_slopeprobe.lua -- pinpoint WHERE/WHY the ÷4 walk step fails to climb a steep slope.
-- PCSX-Redux (LuaJIT). Run: dofile("C:/dev/projects/kf2-60fps/tools/redux_slopeprobe.lua")
-- Then walk INTO the known steep slope (try both walk and run). Read the console.
--
-- Player move routine (RESEARCH §17, recompiled-C verified):
--   func_8002E3F8  stepX=(cos*spd)>>12 @0x8002E448, stepZ=(sin*spd)>>12 @0x8002E478  (WALK ÷4 sites)
--   func_8002E480  propX/Z = step+pos; jal collision 0x80033F38 -> s5 (gpr21)
--                  @0x8002E4C8: s5 ready.  s5!=0 -> BLOCKED (func_8002E59C); s5==0 -> incline path
--   func_8002E4DC  if [0x801E6498] >= 0x40 (steep) -> reproject(add climb vec)+loop; else commit
--   @0x8002E558    reproject applied (stepX += s1=gpr17, stepZ += gpr2)
--   @0x8002E564    COMMIT propX/Z + posY([0x801E646E]->[0x801B2644])
--
-- THE QUESTION: when the ÷4 step is BLOCKED on the slope, is [0x801E6498] (the incline metric) >= 0x40?
--   If YES while walls/trees give <0x40, then "s5!=0 AND incline>=0x40" is a SLOPE-SPECIFIC gate we can
--   cave: on that, redo with a full-size step (the climb the reprojection would have done). If NO (incline
--   is only set on the clear path), there's no clean signal and §17.6 stands.

local A_POST   = 0x8002E4C8   -- post-collision: s5 ready
local A_COMMIT = 0x8002E564   -- committed (moved)
local A_BLOCK  = 0x8002E59C   -- blocked (collision rejected)
local A_REPROJ = 0x8002E558   -- incline reprojection applied
local POSX, POSZ, POSY = 0x801B25F0, 0x801B25F8, 0x801B2644      -- player pos (X/Z word, Y half)
local INCL, INCLA      = 0x801E6498, 0x801E649C                   -- incline metric + angle (words)
local band = bit.band
local function r32(a) local p=PCSX.getMemPtr(); local o=band(a,0x1fffff)
  local v=p[o]+p[o+1]*256+p[o+2]*65536+p[o+3]*16777216; if v>=0x80000000 then v=v-0x100000000 end; return v end
local function r16(a) local p=PCSX.getMemPtr(); local o=band(a,0x1fffff); return p[o]+p[o+1]*256 end
local function reg(nm) return PCSX.getRegisters().GPR.n[nm] end
local function s32(v) if v>=0x80000000 then return v-0x100000000 end return v end

_G.__sp = _G.__sp or {}
local S = _G.__sp
for _,k in ipairs({'a','c','b','r'}) do if S[k] then S[k]:remove() end end
S.on = true
S.coll = 0

-- post-collision: stash the decision state (printed by whichever terminal fires next)
S.a = PCSX.addBreakpoint(A_POST, 'Exec', 4, 'sp_post', function()
  if not S.on then return end
  S.coll = S.coll + 1
  S.last = { stepX = s32(reg('s4')), stepZ = s32(reg('s2')), s5 = reg('s5'),
             incl = r32(INCL), incla = r32(INCLA), x = r32(POSX), z = r32(POSZ), y = r16(POSY),
             coll = S.coll }
end)

local function show(tag)
  local L = S.last
  if not L then print(string.format('[slope] %s (no post-coll state)', tag)); return end
  print(string.format('[slope] %-7s coll#%d  s5=0x%X  incl=%d inclA=%d  step=(%d,%d)  pos=(%d,%d,y=%d)',
        tag, L.coll, L.s5, L.incl, L.incla, L.stepX, L.stepZ, L.x, L.z, L.y))
end

S.c = PCSX.addBreakpoint(A_COMMIT, 'Exec', 4, 'sp_commit', function() if S.on then show('COMMIT') end end)
S.b = PCSX.addBreakpoint(A_BLOCK,  'Exec', 4, 'sp_block',  function() if S.on then show('BLOCKED') end end)
S.r = PCSX.addBreakpoint(A_REPROJ, 'Exec', 4, 'sp_reproj', function()
  if S.on then print(string.format('[slope] REPROJ  s1(addX)=%d  (then re-collides w/ bigger step)', s32(reg('s1')))) end
end)

function spon()  S.on=true;  print('[slope] logging ON -- walk INTO the slope (try walk, then run)') end
function spoff() S.on=false; print('[slope] logging OFF') end
function spstop() for _,k in ipairs({'a','c','b','r'}) do if S[k] then S[k]:remove() end end print('[slope] removed') end
print('[slope] armed. spoff()/spon() to gate noise, spstop() to remove.')
print('  Walk into the slope (BLOCKED every frame?), then hold run. Watch s5 + incl on BLOCKED vs COMMIT.')
