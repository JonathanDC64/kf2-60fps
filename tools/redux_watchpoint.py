#!/usr/bin/env python3
"""Set a GDB write-watchpoint on the player position; when the user walks, the
write fires and we read the PC (the walk/move code) + ra (caller). Args: addr len."""
import socket, struct, urllib.request, sys, time

GDB=("127.0.0.1",3333)
def web(fn):
    try: urllib.request.urlopen(urllib.request.Request(
        "http://localhost:8080/api/v1/execution-flow?function=%s"%fn,method="POST",data=b""),timeout=5).read()
    except Exception as e: print("web",fn,e)

class Gdb:
    def __init__(s): s.s=socket.create_connection(GDB,timeout=30); s.s.settimeout(30)
    def send(s,body):
        ck=sum(body.encode())&0xff
        s.s.sendall(("$%s#%02x"%(body,ck)).encode())
    def recv_pkt(s):
        buf=b""
        while True:
            c=s.s.recv(4096)
            if not c: return None
            buf+=c
            if buf.count(b"#")>0 and len(buf.split(b"#")[-1])>=2:
                # may have leading '+'
                try: body=buf[buf.index(b"$")+1:buf.rindex(b"#")]
                except: return buf
                s.s.sendall(b"+"); return body.decode("latin1")
    def cmd(s,body): s.send(body); return s.recv_pkt()

def regs(g):
    r=g.cmd("g")
    words=[struct.unpack("<I",bytes.fromhex(r[i:i+8]))[0] for i in range(0,min(len(r),38*8),8)]
    names=["zero","at","v0","v1","a0","a1","a2","a3","t0","t1","t2","t3","t4","t5","t6","t7",
           "s0","s1","s2","s3","s4","s5","s6","s7","t8","t9","k0","k1","gp","sp","fp","ra",
           "sr","lo","hi","bad","cause","pc"]
    d={names[i]:words[i] for i in range(min(len(words),38))}
    return d

def main():
    addr=int(sys.argv[1],0) if len(sys.argv)>1 else 0x801b25f0
    ln=int(sys.argv[2],0) if len(sys.argv)>2 else 4
    g=Gdb()
    web("pause"); time.sleep(0.2)
    g.s.sendall(b"\x03"); time.sleep(0.1)
    try: g.s.recv(4096)
    except: pass
    rep=g.cmd("Z2,%x,%x"%(addr,ln))
    print("set watchpoint Z2 @0x%08x reply=%r"%(addr,rep))
    if rep!="OK":
        rep2=g.cmd("Z4,%x,%x"%(addr,ln)); print("try Z4 (access) reply=%r"%rep2)
    print(">>> now WALK (hold forward). waiting for the write to fire...")
    g.send("c")   # continue
    web("resume")
    try:
        pkt=g.recv_pkt()   # blocks until stop (watchpoint hit)
        print("stop packet:",pkt[:60] if pkt else pkt)
        d=regs(g)
        print("  PC=0x%08X  ra=0x%08X  v0=0x%08X a0=0x%08X a1=0x%08X"%(d.get('pc',0),d.get('ra',0),d.get('v0',0),d.get('a0',0),d.get('a1',0)))
    except Exception as e:
        print("no fire / error:",e)

if __name__=="__main__": main()
