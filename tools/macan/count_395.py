import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader

def count395(route_path, label, end_sec=25):
    r = LogReader(route_path); t0=None; n=0; last=None
    for m in r:
        if m.which()!='can': continue
        if t0 is None: t0=m.logMonoTime/1e9
        for c in m.can:
            t=(m.logMonoTime/1e9)-t0
            if t>end_sec: break
            if c.src==2 and c.address==0x395:
                n+=1; last=t
    print(f"{label}: 0x395 bus2 帧数={n} 最后时刻={last:.1f}s" if last else f"{label}: none")

count395('/data/media/0/realdata/00000078--faf5174959--0/rlog.zst','0078融合',25)
count395('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst','0075纯OP',25)
