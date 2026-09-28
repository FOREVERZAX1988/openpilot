import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader

# 0075 纯OP 故障时刻 8.5-10s 详细
print("===== 0075 纯OP 故障前后 (8.5-10.5s) =====")
r = LogReader('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst')
t0=None
rows=[]
for m in r:
    if m.which()!='can': continue
    if t0 is None: t0=m.logMonoTime/1e9
    for c in m.can:
        t=(m.logMonoTime/1e9)-t0
        if 8.5<t<10.5:
            # 记录 bus2 和 bus128 的 ACC_05/395
            if c.address in (0x10D,0x395) and c.src in (2,128):
                rows.append((t,c.src,c.address,c.dat.hex()))
rows.sort()
# 打印关键帧: 0x10D 在 bus2/bus128 st值
print(f"{'t':>8} {'src':>4} {'addr':>5}  data")
prev=None
for t,src,addr,hexd in rows:
    b=bytes.fromhex(hexd)
    if addr==0x10D:
        st=(b[7]>>1)&0x7
        print(f"{t:8.3f} {src:4d} 0x{addr:03X} st={st}  {hexd}")
    else:
        if hexd!=prev:
            print(f"{t:8.3f} {src:4d} 0x{addr:03X}           {hexd}")
            prev=hexd
