"""词级精修审计：输出段内字词间隙、超长词与段间空档候选。

用法:
  python word-audit.py --transcript <asr_raw.json> [--rate 1.1] [--min-gap 0.15]
                       [--min-word 0.5] [--range A B]

只做定位与候选标记，不自动切割。绝对位置和 --range 为原片 PTS 秒。
--min-gap（含显式值）为最终输出秒；默认读取共享 pause-policy.json。
outGap = sourceGap / rate；它是间隔的倍速换算，不是尚未建立的 EDL 输出位置。
--min-word 仍为源词时长，不能把 ASR 词边界当成真实发声边界。
输入要求：ASR 原始 JSON，含 segments[].words[].{word,start,end,probability}
（faster-whisper / faster_whisper 的 `asr_medium_raw.json` 即为此结构）。

判读要点（配合 references/editing-workflow.md）：
  LONG  词时长 ≥ min_word，往往是拖音或把后续停顿并入词尾，需用能量曲线确认。
  GAP   与前词之间 ≥ min_gap，是删停顿的主要候选。
  P     词概率偏低，可能在识别上不可靠，不能据此认定是口误。
  段间空档同样只作候选：底噪高时声学阈值不可靠，宁可少删也不要吞音。
"""
import argparse
import json
import math
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--transcript', required=True, help='ASR 原始 JSON 路径')
    ap.add_argument('--rate', type=float, default=1.1, help='本片实际倍速，默认 1.1')
    ap.add_argument('--min-gap', type=float, help='候选间隔阈值，最终输出秒；默认共享策略')
    ap.add_argument('--min-word', type=float, default=0.5, help='长词候选阈值，原片秒')
    ap.add_argument('--range', nargs=2, type=float, metavar=('LO', 'HI'))
    a = ap.parse_args()
    policy_path = Path(__file__).resolve().parent.parent / 'references' / 'pause-policy.json'
    policy = json.loads(policy_path.read_text(encoding='utf-8-sig'))
    if policy.get('coordinate') != 'final_output_seconds':
        ap.error('pause-policy coordinate 必须为 final_output_seconds')
    min_gap = a.min_gap if a.min_gap is not None else float(policy['candidateSeconds'])
    if not all(math.isfinite(v) and v > 0 for v in (a.rate, min_gap, a.min_word)):
        ap.error('rate、min-gap、min-word 必须是正有限值')

    with open(a.transcript, encoding='utf-8') as fh:
        d = json.load(fh)
    segs = d['segments']
    lo, hi = (a.range if a.range else (None, None))
    print(f'# 词级审计  duration={d.get("duration", float("nan")):.3f}s  '
          f'policy={policy["id"]} rate={a.rate} min_gap_output={min_gap} '
          f'min_gap_source={min_gap * a.rate:.3f} min_word_source={a.min_word} 段数={len(segs)}')
    prev_end = None
    prev_wend = None
    for n, s in enumerate(segs):
        if lo is not None and (s['end'] < lo or s['start'] > hi):
            prev_end = None
            prev_wend = None
            continue
        if prev_end is not None and (s['start'] - prev_end) / a.rate >= min_gap - 1e-9:
            print(f'[段间空档] S{n:03d}  {prev_end:.3f} -> {s["start"]:.3f}  '
                  f'sourceGap={s["start"] - prev_end:.3f}s '
                  f'outGap={(s["start"] - prev_end) / a.rate:.3f}s')
        print(f'S{n:03d}  {s["start"]:.3f}-{s["end"]:.3f}  {s["text"]}')
        if not s.get('words'):
            prev_wend = None  # 无词边界的段不能桥接成已知词间静默。
        for w in s.get('words') or []:
            if lo is not None and (w['end'] < lo or w['start'] > hi):
                prev_wend = None
                continue
            dur = w['end'] - w['start']
            flags = []
            if dur >= a.min_word:
                flags.append(f'LONG={dur:.3f}')
            if prev_wend is not None and (w['start'] - prev_wend) / a.rate >= min_gap - 1e-9:
                flags.append(f'GAP source={w["start"] - prev_wend:.3f} '
                             f'output={(w["start"] - prev_wend) / a.rate:.3f}')
            if w.get('probability', 1) < 0.6:
                flags.append(f'P={w["probability"]:.2f}')
            tag = ('  <<< ' + ' '.join(flags)) if flags else ''
            print(f'    {w["start"]:.3f}-{w["end"]:.3f} {w["word"]}{tag}')
            prev_wend = w['end']
        prev_end = s['end']
    return 0


if __name__ == '__main__':
    sys.exit(main())
