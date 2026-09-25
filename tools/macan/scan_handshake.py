import sys
sys.path.insert(0, '/data/openpilot/openpilot')
from tools.lib.logreader import LogReader
from collections import defaultdict

def scan(route_path, label, start_sec=0, end_sec=20):
    """扫描点火段 bus2(雷达侧) 的报文活动时间轴"""
    print(f"\n========== {label} ==========")
    r = LogReader(route_path)
    # bus2 上的报文: addr -> 首次出现时间, 最后时间, 次数, last_data
    first = {}
    last = {}
    count = defaultdict(int)
    samples = {}
    t0 = None
    n_bus2 = 0
    for m in r:
        if m.which() != 'can':
            continue
        for c in m.can:
            if c.src != 2:  # 只看 bus2 雷达侧
                continue
            if t0 is None:
                t0 = m.logMonoTime / 1e9
            t = (m.logMonoTime / 1e9) - t0
            if t > end_sec:
                continue
            n_bus2 += 1
            a = c.address
            d = c.dat.hex()
            if a not in first:
                first[a] = t
                samples[a] = (t, d)
            last[a] = t
            count[a] += 1
    print(f"bus2 帧数(0-{end_sec}s): {n_bus2}")
    print(f"bus2 出现 {len(first)} 个 CAN ID")
    print(f"{'ADDR':>6} {'HEX':<6} {'first_t':>8} {'last_t':>8} {'count':>6}  first_data")
    for a in sorted(first, key=first.get):
        print(f"0x{a:03X} 0x{a:03X} {first[a]:8.2f} {last[a]:8.2f} {count[a]:6d}  {samples[a][1]}")

# 0078: 融合模式点火段（雷达正常待命，不报错）
scan('/data/media/0/realdata/00000078--faf5174959--0/rlog.zst', '0078 融合 seg0 点火段', 0, 20)
