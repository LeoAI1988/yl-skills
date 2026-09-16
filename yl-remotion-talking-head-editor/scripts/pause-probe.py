"""自适应停顿探测：按区间输出低能量候选（不做自动切割）。

用法:
  python pause-probe.py --audio <16k_mono.wav> --ranges "8.2-11.4,299.0-305.0"
                        [--guard-db 6] [--min-ms 70]

方法：读 16bit 单声道 16kHz WAV，做 170-4500Hz 带通，10ms 窗算 RMS(dB)。
每区间用第 25 百分位作噪声底参考，阈值 = 噪声底 + guard_db。
输出低能量连续段及其边界 dB，用于人工判断是迟疑、思考停顿还是必要留白。

重要边界（见 references/editing-workflow.md）：
- 本工具只提供候选，**不是听审结论**；确认要删的区间必须与词级发声区间不重叠。
- 底噪高时（区间 P10–P90 跨度小于约 15dB）判据不可靠，此时宁可少删也不要吞音。
- 不要按阈值批量切割，也不要把某个固定 dB 当成所有录音的通用静音真值。
时间均为原片 PTS 秒。
"""
import argparse
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfilt


def load_db(path: str) -> tuple[np.ndarray, float]:
    with wave.open(path) as f:
        sr = f.getframerate()
        a = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768
    x = sosfilt(butter(3, [170, 4500], btype='bandpass', fs=sr, output='sos'), a)
    hop = sr // 100
    n = len(x) // hop * hop
    db = 20 * np.log10(np.sqrt(np.mean(x[:n].reshape(-1, hop) ** 2, axis=1)) + 1e-8)
    return db, float(hop) / sr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True, help='16bit 单声道 16kHz WAV')
    ap.add_argument('--ranges', required=True, help='逗号分隔的 a-b 区间，单位秒')
    ap.add_argument('--guard-db', type=float, default=6.0)
    ap.add_argument('--min-ms', type=float, default=70.0)
    a = ap.parse_args()

    ranges = []
    for part in a.ranges.split(','):
        lo, hi = part.split('-')
        ranges.append((float(lo), float(hi)))

    db, dt = load_db(a.audio)
    print(f'# 停顿探测  hop={dt * 1000:.1f}ms  guard_db={a.guard_db}  min_ms={a.min_ms}')
    for lo, hi in ranges:
        i0, i1 = int(lo / dt), int(hi / dt)
        seg = db[i0:i1]
        if not len(seg):
            continue
        floor = float(np.percentile(seg, 25))
        thr = floor + a.guard_db
        quiet = seg < thr
        span = float(np.percentile(seg, 90) - np.percentile(seg, 10))
        warn = '  <<< 底噪高，判据不可靠，宁少删不吞音' if span < 15 else ''
        print(f'\n== 区间 {lo:.3f}-{hi:.3f}  floor(P25)={floor:.1f}dB  阈值={thr:.1f}dB  '
              f'P10={np.percentile(seg, 10):.1f} P50={np.percentile(seg, 50):.1f} '
              f'P90={np.percentile(seg, 90):.1f}{warn}')
        j = 0
        while j < len(quiet):
            if not quiet[j]:
                j += 1
                continue
            k = j
            while k < len(quiet) and quiet[k]:
                k += 1
            t0, t1 = lo + j * dt, lo + k * dt
            if (t1 - t0) * 1000 >= a.min_ms:
                lo_i = max(0, i0 + j - 8)
                hi_i = min(len(db), i0 + k + 8)
                edge = (f'前0.08s均={db[lo_i:i0 + j].mean():.1f}dB'
                        if i0 + j > lo_i else '前=区间起点')
                edge2 = (f'后0.08s均={db[i0 + k:hi_i].mean():.1f}dB'
                         if hi_i > i0 + k else '后=区间终点')
                print(f'   候选 {t0:.3f}-{t1:.3f}  时长={(t1 - t0) * 1000:.0f}ms  '
                      f'最低={seg[j:k].min():.1f}dB  {edge}  {edge2}')
            j = k
    return 0


if __name__ == '__main__':
    sys.exit(main())
