#!/usr/bin/env python3
"""General GDB word-poke: redux_pokew.py addr1 word1 [addr2 word2 ...]
Writes 32-bit words (little-endian in memory) to RAM via PCSX-Redux GDB."""
import socket, urllib.request, sys, time
def web(fn):
    try: urllib.request.urlopen(urllib.request.Request(
        "http://localhost:8080/api/v1/execution-flow?function=%s"%fn,method="POST",data=b""),timeout=5).read()
    except Exception as e: print("web",fn,e)
class Gdb:
    def __init__(s): s.s=socket.create_connection(("127.0.0.1",3333),timeout=10); s.s.settimeout(10)
    def cmd(s,body):
        ck=sum(body.encode())&0xff; s.s.sendall(("$%s#%02x"%(body,ck)).encode())
        buf=b""
        while True:
            c=s.s.recv(4096)
            if not c: break
            buf+=c
            if buf.count(b"#")>0 and len(buf.split(b"#")[-1])>=2: break
        s.s.sendall(b"+"); return buf[buf.index(b"$")+1:buf.rindex(b"#")].decode("latin1")
def le(w): return "%02x%02x%02x%02x"%(w&0xff,(w>>8)&0xff,(w>>16)&0xff,(w>>24)&0xff)
args=sys.argv[1:]
pairs=[(int(args[i],0),int(args[i+1],0)) for i in range(0,len(args),2)]
g=Gdb(); web("pause"); time.sleep(0.2)
g.s.sendall(b"\x03"); time.sleep(0.1)
try: g.s.recv(4096)
except: pass
for addr,word in pairs:
    print("before %08x:"%addr, g.cmd("m%x,4"%addr))
    print("  write %08x = %08x ->"%(addr,word), g.cmd("M%x,4:%s"%(addr,le(word))))
    print("after  %08x:"%addr, g.cmd("m%x,4"%addr))
web("resume"); print("done")
