import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader

def extract_state(route_path, label, end_sec=30):
    """提取 ACC_05(0x10D) 的 Status_ACC(bit57|3) 和 ACC_02(0x30C) Status_Anzeige(bit61|3)"""
    print(f"\n===== {label} =====")
    r = LogReader(route_path); t0=None
    # ACC_05: addr0x10D=269, Status_ACC bit57|3 -> (b[7]>>1)&0x7
    # ACC_02: addr0x30C=780, Status_Anzeige bit61|3 -> (b[7]>>5)&0x7
    acc05_out=[]; acc02_out=[]
    for m in r:
        if m.which()!='can': continue
        if t0 is None: t0=m.logMonoTime/1e9
        for c in m.can:
            t=(m.logMonoTime/1e9)-t0
            if t>end_sec: continue
            if c.src==2:
                b=c.dat
                if c.address==0x10D:
                    st=(b[7]>>1)&0x7
                    acc05_out.append((t,st))
                if c.address==0x30C:
                    st=(b[7]>>5)&0x7
                    acc02_out.append((t,st))
    print("-- ACC_05 Status_ACC 演化 (bus2) --")
    prev=None
    for t,s in acc05_out:
        if s!=prev: print(f"  {t:7.3f}s Status_ACC={s}"); prev=s
    print("-- ACC_02 Status_Anzeige 演化 (bus2) --")
    prev=None
    for t,s in acc02_out:
        if s!=prev: print(f"  {t:7.3f}s Status_Anz={s}"); prev=s

extract_state('/data/media/0/realdata/00000078--faf5174959--0/rlog.zst','0078融合(正常)')
extract_state('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst','0075纯OP(报错)')
