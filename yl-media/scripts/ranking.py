"""Shared five-dimensional percentile score for a verified video cohort."""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path

RULE_VERSION = '3.4-five-dim'
SUPPORTED_RULES = ('3.0-raw-follows', RULE_VERSION)

def rule_description(rule=RULE_VERSION):
    if rule == '3.0-raw-follows':
        return '规则3.0-raw-follows：完播率百分位50%＋单作品涨粉原始数量30%＋三秒完播率百分位20%。涨粉不转百分位、不除播放，分数可超过100。缺任一评分指标不排名，不补零。'
    if rule == RULE_VERSION:
        return '规则3.4-five-dim：完播率百分位35%＋平均播放时长百分位20%＋万播放涨粉百分位10%＋涨粉数百分位25%＋三秒完播率百分位10%。五项均为组内百分位，满分100；缺任一评分指标不排名，不补零。'
    raise ValueError('Unsupported ranking rule: ' + str(rule))

# 完播率 / 平均播放时长 / 万播放涨粉 / 涨粉数 / 三秒完播率
WEIGHTS = (
    ('completion', .35),
    ('watch_seconds', .20),
    ('follows_per_10k', .10),
    ('follows', .25),
    ('three_sec', .10),
)

def number(value):
    if value is None or value == '': return None
    if isinstance(value, bool): raise ValueError('Boolean is not a metric')
    try: n = float(value)
    except (ValueError, TypeError): raise ValueError('Invalid numeric metric') from None
    if not math.isfinite(n) or n < 0: raise ValueError('Metric must be finite and nonnegative')
    return n

def pick(row, fields):
    values = [number(row[k]) for k in fields if k in row and row[k] not in (None, '')]
    if values and any(v != values[0] for v in values): raise ValueError('Conflicting metric aliases')
    return values[0] if values else None

def percentile_table(values):
    """升序百分位 0–100；并列取最低位置；单样本为 0。"""
    ordered = sorted(values)
    table = {}
    for i, v in enumerate(ordered):
        table.setdefault(v, i / max(1, len(ordered) - 1) * 100)
    return table

def rank(rows, rule=RULE_VERSION):
    rule_description(rule)  # Reject unknown rules before changing any records.
    result = [dict(r) for r in rows]
    valid = []
    for i, r in enumerate(result):
        eligibility = str(r.get('ranking_eligible', 'true')).lower()
        if eligibility not in ('true', 'false', '1', '0'):
            raise ValueError('ranking_eligible must be an explicit boolean when supplied')
        completion = pick(r, ('完播率','completion_pct'))
        watch = pick(r, ('平均播放时长','平均观看时长','均观看秒','watch_seconds','avgPlayTimeSec'))
        follows = pick(r, ('关注','涨粉数','follows'))
        follows10k = pick(r, ('万播放涨粉','follows_per_10k'))
        views = pick(r, ('播放','播放量','views'))
        flip = pick(r, ('快速划走率','fast_flip_pct'))
        three = pick(r, ('三秒完播率','three_sec_pct'))
        for n in (completion, flip, three):
            if n is not None and n > 100: raise ValueError('Percentage must be between 0 and 100')
        if flip is not None:
            derived = round(100-flip, 2)
            if three is not None and abs(three-derived) > .011: raise ValueError('Three-second metric disagrees with adopted formula')
            three = derived
        if follows10k is None and follows is not None and views is not None:
            follows10k = round(follows / views * 10000, 1) if views else 0.0
        r.update(三秒完播率=three, 综合排名=None, 综合评分=None, 排名规则版本=rule)
        required = (completion, follows, three) if rule == '3.0-raw-follows' else (completion, follows, follows10k, three, watch)
        if eligibility in ('true', '1') and all(x is not None for x in required):
            valid.append((i, completion, follows, follows10k, three, watch))
    idx = {'completion': 1, 'follows': 2, 'follows_per_10k': 3, 'three_sec': 4, 'watch_seconds': 5}
    keys = ('completion', 'three_sec') if rule == '3.0-raw-follows' else tuple(idx)
    pct = {k: percentile_table([x[idx[k]] for x in valid]) for k in keys}
    for values in valid:
        if rule == '3.0-raw-follows':
            score = round(pct['completion'][values[1]], 1) * .50 + values[2] * .30 + round(pct['three_sec'][values[4]], 1) * .20
        else:
            score = sum(round(pct[key][values[idx[key]]], 1) * weight for key, weight in WEIGHTS)
        result[values[0]]['综合评分'] = round(score, 2)
    ordered = sorted((r for r in result if r['综合评分'] is not None), key=lambda r:-r['综合评分'])
    for i,r in enumerate(ordered,1): r['综合排名'] = i
    return sorted(result,key=lambda r:r['综合排名'] if r['综合排名'] is not None else float('inf'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--rule',choices=SUPPORTED_RULES,default=RULE_VERSION);a=p.parse_args()
    with a.input.open(encoding='utf-8-sig',newline='') as f: data=list(csv.DictReader(f))
    result={'rule_version':a.rule,'rule_description':rule_description(a.rule),'rows':rank(data,rule=a.rule),'scope':'One previously verified comparable cohort; not automatic platform coverage validation'}
    if a.output.exists(): raise ValueError('Do not overwrite a prior ranking; choose a new output')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'ranked','rule_version':a.rule,'rows':len(data)}))

if __name__=='__main__':main()
