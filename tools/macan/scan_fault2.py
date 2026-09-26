import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader

# 0075: st=7 之后 0x10D 在 bus2 的持续 + 0x395 是否停发; 检查 9.25s 之后
print("===== 0075 纯OP bus2: 9.0-15s 0x10D / 0x395 =====")
r = LogReader('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst')
t0=None
for m in r:
    if m.which()!='can': continue
    if t0 is None: t0=m.logMonoTime/1e9
    for c in m.can:
        t=(m.logMonoTime/1e9)-t0
        if 9.0<t<15.0 and c.src==2 and c.address in (0x10D,0x395):
            b=c.dat
            if c.address==0x10D:
                st=(b[7]>>1)&0x7
                if st==7:
                    print(f"  {t:7.3f}s 0x10D st=7 {c.dat.hex()}  [雷达故障广播]")
                # 只在状态变化时打印, 这里打印首条
            else:
                print(f"  {t:7.3f}s 0x395 {c.dat.hex()}")
