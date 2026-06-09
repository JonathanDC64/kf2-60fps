#!/usr/bin/env python3
"""Frame-step N frames and dump a memory region each frame, then report every
2-byte field whose value changed across frames as a per-frame sequence. Used to
spot per-frame counters (animation timers, AI state) in a struct.
Usage: redux_framewatch.py <base> <length> <steps>
"""
import socket, urllib.request, sys, time, struct

GDB=("127.0.0.1",3333)
FRAME_BP=0x80019614
def web(fn):
    try: urllib.request.urlopen(urllib.request.Request(
        "http://localhost:8080/api/v1/execution-flow?function=%s"%fn,method="POST",data=b""),timeout=5).read()
    except Exception as e: print("web",fn,e)
class Gdb:
    def __init__(s): s.s=socket.create_connection(GDB,timeout=20); s.s.settimeout(20)
    def send(s,b):
        ck=sum(b.encode())&0xff; s.s.sendall(("$%s#%02x"%(b,ck)).encode())
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
    def cmd(s,b): s.send(b); return s.recv_pkt()
    def rd(s,a,n):
        r=s.cmd("m%x,%x"%(a,n))
        try: return bytes.fromhex(r)
        except: return None

def main():
    base=int(sys.argv[1],0); length=int(sys.argv[2],0); steps=int(sys.argv[3],0) if len(sys.argv)>3 else 12
    g=Gdb(); web("pause"); time.sleep(0.2); g.s.sendall(b"\x03"); time.sleep(0.1)
    try: g.s.recv(4096)
    except: pass
    print("Z0:",g.cmd("Z0,%x,4"%FRAME_BP))
    frames=[]
    for f in range(steps):
        g.send("c")
        if f==0: web("resume")
        if g.recv_pkt() is None: print("no stop @%d"%f); break
        b=g.rd(base,length); frames.append(b)
    g.cmd("z0,%x,4"%FRAME_BP); web("resume")
    if not frames or frames[0] is None: print("read fail"); return
    n=min(len(b) for b in frames if b)
    print("changed 2-byte fields over %d frames (off: seq):"%len(frames))
    for off in range(0,n-1,2):
        seq=[struct.unpack_from("<h",fr,off)[0] for fr in frames if fr and len(fr)>=off+2]
        if len(set(seq))>1:
            d=[seq[i+1]-seq[i] for i in range(len(seq)-1)]
            tag=" <== steady" if len(set(d))<=2 and all(abs(x)<64 for x in d) else ""
            print("  +0x%02x (0x%08X): %s%s"%(off, base+off, seq, tag))
if __name__=="__main__": main()
