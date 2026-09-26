import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader
from collections import defaultdict

def scan(route_path, label, end_sec=20):
    print(f"\n========== {label} ==========")
    r = LogReader(route_path)
    first = {}; last = {}; count = defaultdict(int); samples = {}
    t0 = None; n=0
    # 标记 bus0/1/2/128 上 ACC 相关 ID 的出现
    acc_ids = {0x10D, 0x30C, 0x324, 0x104, 0x395}
    bus_on_acc = defaultdict(lambda: defaultdict(int))  # addr -> bus -> count
    for m in r:
        if m.which() != 'can': continue
        t = (m.logMonoTime/1e9) if t0 is not None else 0
        for c in m.can:
            if t0 is None: t0 = m.logMonoTime/1e9
            if c.src == 2:
                t = (m.logMonoTime/1e9)-t0
                if t > end_sec: continue
                n += 1
                a = c.address
                if a not in first: first[a]=t; samples[a]=c.dat.hex()
                last[a]=t; count[a]+=1
            if c.address in acc_ids:
                bus_on_acc[c.address][c.src] += 1
    print(f"bus2 帧数: {n}, CAN ID 数: {len(first)}")
    print(f"{'ADDR':>5} {'first_t':>8} {'last_t':>8} {'count':>7}  first_data")
    for a in sorted(first, key=first.get):
        print(f"0x{a:03X} {first[a]:8.2f} {last[a]:8.2f} {count[a]:7d}  {samples[a]}")
    print("--- ACC相关ID各bus出现次数 ---")
    for a in sorted(acc_ids):
        b = dict(bus_on_acc[a])
        print(f"0x{a:03X}: {b}")

scan('/data/media/0/realdata/00000075--77231a5ef1--0/rlog.zst', '0075 纯OP seg0 点火段(报错)', 20)
