#!/usr/bin/env python3
"""Deterministic frame-step + per-frame memory sampling via GDB.
Sets a Z0 breakpoint at the once-per-frame sync fn (FUN_80019614 default), then
continues N times (= N frames), reading the given addresses each frame.
Usage: redux_framestep.py <steps> <addr:size> [addr:size ...]   (size in bytes 1/2/4)
"""
import socket, struct, urllib.request, sys, time

GDB=("127.0.0.1",3333)
FRAME_BP=0x80019614   # FUN_80019614 = per-frame vblank-cap/sync (called once/frame)

def web(fn):
    try: urllib.request.urlopen(urllib.request.Request(
        "http://localhost:8080/api/v1/execution-flow?function=%s"%fn,method="POST",data=b""),timeout=5).read()
    except Exception as e: print("web",fn,e)

class Gdb:
    def __init__(s): s.s=socket.create_connection(GDB,timeout=20); s.s.settimeout(20)
    def send(s,body):
        ck=sum(body.encode())&0xff
        s.s.sendall(("$%s#%02x"%(body,ck)).encode())
    def recv_pkt(s):
        buf=b""
        while True:
            c=s.s.recv(4096)
            if not c: return None
            buf+=c
            if b"#" in buf and len(buf.split(b"#")[-1])>=2:
                try: body=buf[buf.index(b"$")+1:buf.rindex(b"#")]
                except: return None
                s.s.sendall(b"+"); return body.decode("latin1")
    def cmd(s,body): s.send(body); return s.recv_pkt()
    def rdmem(s,addr,n):
        r=s.cmd("m%x,%x"%(addr,n))
        if r is None or (len(r)>=3 and r[0]=='E' and len(r)==3): return None
        try: return bytes.fromhex(r)
        except: return None
    def wrmem(s,addr,hexb): return s.cmd("M%x,%x:%s"%(addr,len(hexb)//2,hexb))

def val(b,sz):
    if b is None: return None
    if sz==1: return b[0]
    if sz==2: return struct.unpack("<h",b[:2])[0]
    return struct.unpack("<i",b[:4])[0]

def main():
    steps=int(sys.argv[1],0) if len(sys.argv)>1 else 6
    targets=[]; poke=None
    for a in sys.argv[2:]:
        if a.startswith("poke="):
            ad,_,hb=a[5:].partition(":"); poke=(int(ad,0), hb)
            continue
        addr,_,sz=a.partition(":"); targets.append((int(addr,0), int(sz) if sz else 4))
    g=Gdb()
    web("pause"); time.sleep(0.2)
    g.s.sendall(b"\x03"); time.sleep(0.1)
    try: g.s.recv(4096)
    except: pass
    rep=g.cmd("Z0,%x,4"%FRAME_BP)
    print("set Z0 breakpoint @0x%08x reply=%r"%(FRAME_BP,rep))
    if poke: print("poke @0x%x = %s -> %r"%(poke[0],poke[1],g.wrmem(poke[0],poke[1])))
    print("frame | PC       | "+" | ".join("0x%08X(%d)"%(a,s) for a,s in targets))
    for f in range(steps):
        g.send("c");
        if f==0: web("resume")
        pkt=g.recv_pkt()
        if pkt is None: print("  (no stop packet at frame %d)"%f); break
        # read PC via 'g' is heavy; infer from breakpoint. read targets:
        vals=[val(g.rdmem(a,s),s) for a,s in targets]
        print("  %3d  | (bp)     | "%f + " | ".join(("%d"%v if v is not None else "err") for v in vals))
    g.cmd("z0,%x,4"%FRAME_BP)   # remove bp
    web("resume")

if __name__=="__main__": main()
