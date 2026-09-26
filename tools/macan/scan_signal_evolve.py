import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader

def probe(route_path, label, addr, bitinfo, end_sec=20):
    """抽取指定 addr 在 bus2 上的字节随时间变化"""
    print(f"\n===== {label}: 0x{addr:03X} ({bitinfo}) =====")
    r = LogReader(route_path)
    t0=None; prev=None; n=0
    for m in r:
        if m.which()!='can': continue
        if t0 is None: t0=m.logMonoTime/1e9
        t=(m.logMonoTime/1e9)-t0
        if t>end_sec: break
        for c in m.can:
            if c.src==2 and c.address==addr:
                d=c.dat.hex()
                if d!=prev:
                    print(f"  {t:7.3f}s  {d}")
                    prev=d
                n+=1
    print(f"  total frames(bus2): {n}")

for route,label,segs in [('/data/media/0/realdata/00000078--faf5174959--0/rlog.zst','0078融合',20),
                          ('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst','0075纯OP',20)]:
    probe(route,label,0x385,'握手/自检报文(点火瞬现)',20)
