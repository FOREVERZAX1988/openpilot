import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader

def status_05(route_path, label, end_sec=25):
    """ACC_05(0x10D)的 Status_ACC (bit60|3) 演化 + 0x395雷达状态"""
    print(f"\n===== {label} ACC_05(0x10D) Status 演化 =====")
    r = LogReader(route_path)
    t0=None
    for m in r:
        if m.which()!='can': continue
        if t0 is None: t0=m.logMonoTime/1e9
        for c in m.can:
            if c.src==2 and c.address==0x10D:
                t=(m.logMonoTime/1e9)-t0
                if t>end_sec: break
                b=c.dat
                # Status_ACC: bit60|3 -> byte7 bit4-6
                status = (b[7]>>4)&0x7
                # can't easily do multi-line, collect
    # redo collecting tuples
    r = LogReader(route_path); t0=None; out=[]
    for m in r:
        if m.which()!='can': continue
        if t0 is None: t0=m.logMonoTime/1e9
        for c in m.can:
            if c.src==2 and c.address==0x10D:
                t=(m.logMonoTime/1e9)-t0
                if t>25: break
                b=c.dat
                status=(b[7]>>4)&0x7
                out.append((t,status))
    # print transitions
    prev=None
    for t,s in out:
        if s!=prev:
            print(f"  {t:7.3f}s  Status_ACC={s}")
            prev=s

def radar_395(route_path, label, end_sec=25):
    print(f"\n===== {label} 雷达状态 0x395 首字节/全帧演化 =====")
    r = LogReader(route_path); t0=None; prev=None
    for m in r:
        if m.which()!='can': continue
        if t0 is None: t0=m.logMonoTime/1e9
        for c in m.can:
            if c.src==2 and c.address==0x395:
                t=(m.logMonoTime/1e9)-t0
                if t>end_sec: break
                d=c.dat.hex()
                if d!=prev:
                    print(f"  {t:7.3f}s  {d}")
                    prev=d

for route,label in [('/data/media/0/realdata/00000078--faf5174959--0/rlog.zst','0078融合'),
                    ('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst','0075纯OP')]:
    status_05(route,label)
    radar_395(route,label)
