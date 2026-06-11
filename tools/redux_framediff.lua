-- KF2 frame-synced read-only diff (PCSX-Redux / LuaJIT).
-- Hooks the once-per-frame cap fn (FUN_80019614) and counts, per halfword in a
-- region, how many frames it changed. Read-only (no mem writes) -> stable.
-- After TARGET frames it writes the most-frequently-changing halfwords to a file
-- and disarms itself. Stand still facing the fire while it runs.
--
-- Run: dofile([[C:\dev\projects\kingsfield2-recomp\KF2Recomp\kf2_framediff.lua]])

local ffi   = require('ffi')
local LO     = 0x80180000     -- region start (sprite arrays .. map data)
local HI     = 0x801e0000     -- region end
local TARGET = 80             -- frames to sample
local OUT    = [[C:\dev\projects\kingsfield2-recomp\KF2Recomp\framediff.txt]]

if kf2fd then kf2fd:remove(); kf2fd = nil end

local mem   = PCSX.getMemPtr()
local n     = (HI - LO) / 2                       -- halfword count
local lo    = LO % 0x200000
local prev  = ffi.new('uint16_t[?]', n)
local cnt   = ffi.new('uint16_t[?]', n)
local vmin  = ffi.new('uint16_t[?]', n)
local vmax  = ffi.new('uint16_t[?]', n)
local frame = 0
local hw    = ffi.cast('uint16_t*', mem + lo)     -- uint16 view at region base

for i = 0, n - 1 do prev[i] = hw[i]; vmin[i] = hw[i]; vmax[i] = hw[i] end   -- seed

kf2fd = PCSX.addBreakpoint(0x80019614, 'Exec', 4, 'kf2-framediff', function()
  pcall(function()
    frame = frame + 1
    for i = 0, n - 1 do
      local v = hw[i]
      if v ~= prev[i] then cnt[i] = cnt[i] + 1; prev[i] = v end
      if v < vmin[i] then vmin[i] = v end
      if v > vmax[i] then vmax[i] = v end
    end
    if frame >= TARGET then
      local f = io.open(OUT, 'w')
      f:write(string.format('# region 0x%08x-0x%08x  frames=%d (changes>=6)\n', LO, HI, frame))
      for i = 0, n - 1 do
        if cnt[i] >= 6 then
          f:write(string.format('0x%08x  changes=%-3d range=%d..%d span=%d  val=%d\n',
            LO + i*2, cnt[i], vmin[i], vmax[i], vmax[i]-vmin[i], hw[i]))
        end
      end
      f:close()
      kf2fd:remove(); kf2fd = nil
      print('KF2 framediff done -> ' .. OUT)
    end
  end)
end)

print(string.format('KF2 framediff armed: sampling 0x%08x-0x%08x for %d frames...', LO, HI, TARGET))
