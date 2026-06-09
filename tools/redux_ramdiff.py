#!/usr/bin/env python3
"""Capture two full-RAM snapshots ~1.5s apart (player standing still) and diff,
to find a moving enemy's position (coordinate-magnitude 32-bit words changing by
movement-like deltas) and animation/timer counters."""
import urllib.request, struct, time
def rd():
    return urllib.request.urlopen("http://localhost:8080/api/v1/cpu/ram/raw?offset=0&size=2097152",timeout=15).read()
a=rd(); time.sleep(1.5); b=rd()
print("captured 2 snapshots, %d bytes"%len(a))
# scan object/state region 0x180000-0x1d4000 for changed 32-bit words
LO,HI=0x180000,0x1d4000
changed=[]
for off in range(LO,HI,4):
    va=struct.unpack_from("<i",a,off)[0]; vb=struct.unpack_from("<i",b,off)[0]
    if va!=vb:
        changed.append((off,va,vb))
print("changed words in 0x%X-0x%X: %d"%(LO,HI,len(changed)))
# coordinate-like: large magnitude (|v|>0x2000) changing by a moderate delta (<0x4000)
print("=== coordinate-like changes (enemy position candidates) ===")
cnt=0
for off,va,vb in changed:
    d=vb-va
    if 0x2000<abs(va)<0x400000 and 0<abs(d)<0x4000:
        print("  0x%08X: %d -> %d (d=%+d)"%(off|0x80000000,va,vb,d)); cnt+=1
        if cnt>40: break
print("=== small counters (timers/anim) sample ===")
cnt=0
for off,va,vb in changed:
    if 0<=va<0x1000 and 0<=vb<0x1000 and abs(vb-va)<64:
        print("  0x%08X: %d -> %d"%(off|0x80000000,va,vb)); cnt+=1
        if cnt>15: break
