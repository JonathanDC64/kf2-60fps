-- redux_enemydmg.lua -- diagnose the "enemies deal 4x damage at 60fps" bug.
-- PCSX-Redux (LuaJIT). Run: dofile("C:/dev/projects/kf2-60fps/tools/redux_enemydmg.lua")
-- Then stand next to ONE enemy, let it land ONE attack swing, and read the console.
--
-- What it answers (see RESEARCH.md ?18):
--   * FUN_8002ab18 (0x8002AB18) = resolve-a-hit  (damage = (hi>>2) - defense)
--   * FUN_8002a6f4 (0x8002A6F4) = apply-damage    (HP -= a1)   <- a1 = final damage dealt
--   * frame ticks via 0x80019614 (1 call/frame) give a wall-clock-independent timeline.
-- Hypothesis A (frequency/per-frame): apply fires MANY times per swing, clustered in adjacent frames.
-- Hypothesis B (magnitude):           apply fires ONCE per swing but with a 4x-too-large a1.
-- Compare the SAME swing on the unpatched(30fps) vs patched(60fps) ROM:
--   A => 60fps shows ~4x the applies per swing (gate the hit cadence).
--   B => same count, a1 differs (a magnitude bug instead).

local HIT   = 0x8002AB18   -- resolve-a-hit (enemy attack lands)
local APPLY = 0x8002A6F4   -- apply-damage to player HP
local FRAME = 0x80019614   -- per-frame function (1 call/frame)
local HP    = 0x801b24fc   -- player HP (u16)
local band  = bit.band
local function r16(a) local p=PCSX.getMemPtr(); local o=band(a,0x1fffff); return p[o]+p[o+1]*256 end

_G.__ed = _G.__ed or {}
local S = _G.__ed
for _,k in ipairs({'fb','hb','ab'}) do if S[k] then S[k]:remove() end end
S.frame, S.hits, S.applies = 0, 0, 0
S.lastHitF, S.lastApplyF = -999, -999
S.swing = 0          -- a "swing" = a hit burst separated by >15 idle frames

S.fb = PCSX.addBreakpoint(FRAME, 'Exec', 4, 'ed_frame', function()
  S.frame = S.frame + 1
end)

S.hb = PCSX.addBreakpoint(HIT, 'Exec', 4, 'ed_hit', function()
  S.hits = S.hits + 1
  local r  = PCSX.getRegisters()
  local a1 = r.GPR.n.a1
  local ra = r.GPR.n.ra
  if a1 >= 0x80000000 then a1 = a1 - 0x100000000 end
  print(string.format('HIT   f=%-6d dmg(a1)=%-6d caller(ra)=0x%08X  HP=%d', S.frame, a1, ra, r16(HP)))
  S.lastHitF = S.frame
end)

S.ab = PCSX.addBreakpoint(APPLY, 'Exec', 4, 'ed_apply', function()
  S.applies = S.applies + 1
  local r  = PCSX.getRegisters()
  local a1 = r.GPR.n.a1
  if a1 >= 0x80000000 then a1 = a1 - 0x100000000 end
  local gap = S.frame - S.lastApplyF
  if gap > 15 then S.swing = S.swing + 1 end   -- new swing after an idle gap
  print(string.format('APPLY f=%-6d dmg(a1)=%-6d gap=%-4d swing#=%d  HP_before=%d',
        S.frame, a1, gap, S.swing, r16(HP)))
  S.lastApplyF = S.frame
end)

function edstat()
  print(string.format('[enemydmg] frames=%d  hits(8002ab18)=%d  applies(8002a6f4)=%d  swings=%d  applies/swing=%.2f',
    S.frame, S.hits, S.applies, S.swing, S.swing>0 and S.applies/S.swing or 0))
end
function edreset() S.frame,S.hits,S.applies,S.swing=0,0,0,0; S.lastHitF,S.lastApplyF=-999,-999; print('[enemydmg] counters reset') end
function edstop() for _,k in ipairs({'fb','hb','ab'}) do if S[k] then S[k]:remove() end end print('[enemydmg] off') end

print('[enemydmg] armed. Take ONE enemy swing. APPLY lines = real HP hits.')
print('  edstat() = summary, edreset() = zero counters (call before a clean swing), edstop() = remove.')
