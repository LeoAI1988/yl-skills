"""Build a reproducible local review from normalized, evidence-linked JSON.

No network access. Personal source adapters live outside the Skill core.
"""
from __future__ import annotations
import argparse
import html
import importlib.util
import json
import statistics
import hashlib
from decimal import Decimal
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


def ratio(a, b, scale=100):
    return a / b * scale if a is not None and b else None


def mean(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return statistics.mean(values) if values else None


def total(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return sum(values) if values else None


def money_total(rows, field='amount'):
    return float(sum((Decimal(str(r[field])) for r in rows), Decimal('0')).quantize(Decimal('.01')))


def mask_contact(value):
    value = str(value or '')
    if not value:
        return ''
    return value[:3] + '*' * max(4, len(value) - 7) + value[-4:] if len(value) > 7 else '*' * len(value)


def region_label(order):
    """Only verified structured region fields; never infer from phone/name."""
    values = list(dict.fromkeys(str(order.get(k) or '').strip() for k in ('province', 'city')))
    values = [v for v in values if v and '*' not in v]
    return ' · '.join(values) if values else '未获取省市'


def opening(segments, text, seconds=5):
    selected = [s for s in segments if s['start'] < seconds and s['end'] > 0]
    if selected:
        end = max(s['end'] for s in selected)
        return {'text': ''.join(s['text'] for s in selected), 'start': selected[0]['start'],
                'end': end, 'exact': end <= seconds,
                'label': f"原始分段 {selected[0]['start']:g}–{end:g} 秒" + ('（跨过 5 秒边界）' if end > seconds else '')}
    return {'text': text.split('。')[0] + ('。' if '。' in text else ''),
            'start': None, 'end': None, 'exact': False, 'label': '首句参考；无精确时间边界'}


def summarize(data):
    meta = data['meta']
    posts = data['posts']
    ids = [r['publication_id'] for r in posts]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and i for i in ids):
        raise ValueError('Publication IDs must be unique nonempty strings')
    calendar_posts = [r for r in posts if meta['from'] <= r['date'] <= meta['to'] and r['public']]
    eligible = [r for r in calendar_posts if r['mature']]
    videos = [r for r in eligible if r['content_type'] == 'video']
    images = [r for r in eligible if r['content_type'] == 'image']
    for r in images:
        if any(r.get(k) is not None for k in ('completion_pct', 'three_sec_pct', 'watch_seconds', 'duration_seconds')):
            raise ValueError('Image-only posts must have null video metrics')
    ranking_path = Path(__file__).resolve().parents[2] / 'yl-media/scripts/ranking.py'
    spec = importlib.util.spec_from_file_location('yl_shared_ranking', ranking_path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    ranked = [r for r in mod.rank(videos) if r['综合评分'] is not None]
    hits = [r for r in videos if r.get('views') is not None and r['views'] >= meta['hit_threshold']]
    segments = []
    for a, b in meta['segments']:
        group = [r for r in videos if a <= r['date'] <= b]
        h = [r for r in group if r.get('views') is not None and r['views'] >= meta['hit_threshold']]
        values = sorted(r['views'] for r in group if r.get('views') is not None)
        segments.append({'from': a, 'to': b, 'n': len(group), 'views': total(group, 'views'),
                         'mean_views': mean(group, 'views'), 'completion': mean(group, 'completion_pct'),
                         'watch': mean(group, 'watch_seconds'), 'three': mean(group, 'three_sec_pct'),
                         'follows': total(group, 'follows'), 'shares': total(group, 'shares'),
                         'per10k': ratio(total(group, 'follows'), total(group, 'views'), 10000),
                         'hits': len(h), 'hit_rate': ratio(len(h), len(group)), 'hit_views': total(h, 'views') if h else 0,
                         'median': statistics.median(values) if values else None,
                         'trimmed_median': statistics.median(values[1:-1]) if len(values) >= 3 else None,
                         'trimmed_mean': statistics.mean(values[1:-1]) if len(values) >= 3 else None,
                         'trimmed_n': max(0, len(values)-2)})
    daily = []
    day = date.fromisoformat(meta['from']); end = date.fromisoformat(meta['to'])
    while day <= end:
        ds = day.isoformat(); g = [r for r in calendar_posts if r['date'] == ds]
        v = [r for r in g if r['content_type'] == 'video']
        known = ds not in meta.get('calendar_missing_dates', [])
        daily.append({'date': ds, 'videos': len(v) if known else None,
                      'images': sum(r['content_type'] == 'image' for r in g) if known else None,
                      'unknown': sum(r['content_type'] not in ('video', 'image') for r in g) if known else None,
                      'count': len(g) if known else None, 'covered': known,
                      'views': sum(r['views'] for r in v) if known and all(r.get('views') is not None for r in v) else None})
        day += timedelta(days=1)
    paid = [o for o in data['orders'] if o['paid']]
    if len({o['order_id'] for o in data['orders']}) != len(data['orders']):
        raise ValueError('Duplicate orders')
    by_id = {r['publication_id']: r for r in videos}
    products = []
    for product in data['products']:
        product_orders = [o for o in paid if o['product_id'] == product['product_id']]
        attribution = [a for a in data['attribution'] if a['product_id'] == product['product_id'] and a['publication_id'] in by_id]
        attributed_hits = [a for a in attribution if by_id[a['publication_id']]['views'] >= meta['hit_threshold']]
        products.append({**product, 'orders': len(product_orders), 'amount': money_total(product_orders),
                         'attributed_orders': sum(a['orders'] for a in attribution),
                         'attributed_amount': money_total(attribution),
                         'attributed_video_n': len({a['publication_id'] for a in attribution}),
                         'hit_video_n': len({a['publication_id'] for a in attributed_hits}),
                         'hit_amount': money_total(attributed_hits),
                         'hit_orders': sum(a['orders'] for a in attributed_hits)})
    paid_amount = money_total(paid)
    for product in products:
        product['order_share'] = ratio(product['orders'], len(paid))
        product['amount_share'] = ratio(product['amount'], paid_amount)
    return {'videos': videos, 'images': images, 'eligible': eligible, 'ranked': ranked,
            'hits': hits, 'segments': segments, 'daily': daily, 'products': products,
            'paid_orders': paid, 'rule_version': mod.RULE_VERSION,
            'views': total(videos, 'views'), 'follows': total(videos, 'follows'),
            'shares': total(videos, 'shares'), 'watch': mean(videos, 'watch_seconds'),
            'zero_dates': [r['date'] for r in daily if r['count'] == 0],
            'active_days': sum(bool(r['count']) for r in daily),
            'missing_days': sum(not r['covered'] for r in daily)}


def fmt(value, decimals=0, suffix=''):
    return '—' if value is None else f'{value:,.{decimals}f}{suffix}'


def opening_duration(transcript):
    op = transcript.get('opening', {})
    if op.get('start') is not None and op.get('end') is not None:
        return f"约 {max(1, round(op['end'] - op['start']))} 秒"
    return '时长待确认'


def product_colors(data):
    palette = ['#ff9d63', '#6fc5ff', '#bda4ff', '#7cdfbd']
    return {p['product_id']: palette[i % len(palette)] for i, p in enumerate(data['products'])}


def sales_series(data, s):
    """Daily paid amounts, all-product total; unknown dates stay null."""
    selected = data['meta'].get('sales_chart_product_ids', [p['product_id'] for p in data['products'][:2]])
    if len(selected) != 2 or len(set(selected)) != 2:
        raise ValueError('Sales chart requires two distinct products')
    known_ids = {p['product_id'] for p in data['products']}
    if not set(selected) <= known_ids:
        raise ValueError('Unknown chart product')
    rows = []
    day = date.fromisoformat(data['meta'].get('orders_from', data['meta']['from']))
    end = date.fromisoformat(data['meta'].get('orders_to', data['meta']['to']))
    while day <= end:
        ds = day.isoformat()
        orders = [o for o in s['paid_orders'] if str(o.get('paid_at') or o['time'])[:10] == ds]
        known = ds not in data['meta'].get('orders_missing_dates', [])
        rows.append({'date': ds, 'total': money_total(orders) if known else None,
                     'products': {pid: money_total([o for o in orders if o['product_id'] == pid]) if known else None for pid in selected}})
        day += timedelta(days=1)
    return selected, rows


def sales_chart(data, s):
    selected, rows = sales_series(data, s)
    colors = product_colors(data)
    labels = {p['product_id']: p['label'] for p in data['products']}
    series = [(pid, labels[pid], colors[pid]) for pid in selected] + [('total', '总成交金额', '#ff757d')]
    def value(r, key): return r['total'] if key == 'total' else r['products'][key]
    ymax = max((r['total'] or 0 for r in rows), default=0) or 1
    ymax = max(100, (int(ymax / 100) + 1) * 100)
    left, top, width, height = 85, 35, 1160, 280
    x = lambda i: left + i * width / max(1, len(rows) - 1)
    y = lambda v: top + height - v / ymax * height
    parts = ['<div class="sales-legend">'+''.join(f'<span style="color:{color}">━ {html.escape(label)}</span>' for _,label,color in series)+'</div>',
             '<div class="chart sales-chart"><svg viewBox="0 0 1280 380" role="img" aria-label="每日成交金额：两种产品与总金额三条曲线">']
    for i in range(5):
        amount = ymax * i / 4
        parts.append(f'<line x1="{left}" y1="{y(amount)}" x2="{left+width}" y2="{y(amount)}" stroke="#303844"/><text x="{left-12}" y="{y(amount)+5}" text-anchor="end" fill="#adb8c6" font-size="13">{amount:,.0f}</text>')
    parts.append('<text x="16" y="20" fill="#adb8c6" font-size="13">金额 / 元</text>')
    for i,r in enumerate(rows):
        if i % max(1, len(rows)//8) == 0 or i == len(rows)-1:
            parts.append(f'<text x="{x(i)}" y="345" text-anchor="middle" fill="#adb8c6" font-size="13">{r["date"][5:]}</text>')
    # Total first, dashed: product and total remain visible when they coincide.
    for key,label,color in reversed(series):
        points=[]
        def flush():
            if points:
                dash = ' stroke-dasharray="8 6"' if key=='total' else ''
                parts.append(f'<polyline data-series="{html.escape(key)}" points="'+ ' '.join(points)+f'" fill="none" stroke="{color}" stroke-width="3"{dash}/>' )
                points.clear()
        for i,r in enumerate(rows):
            v=value(r,key)
            if v is None: flush(); continue
            points.append(f'{x(i):.2f},{y(v):.2f}')
        flush()
    for i,r in enumerate(rows):
        desc = r['date']+'；'+'；'.join(label+'：'+('未取得' if value(r,key) is None else '¥'+fmt(value(r,key),2)) for key,label,_ in series)
        parts.append(f'<rect x="{x(i)-width/max(1,len(rows)-1)/2}" y="{top}" width="{max(8,width/max(1,len(rows)-1))}" height="{height}" fill="transparent"><title>{html.escape(desc)}</title></rect>')
    parts.append('</svg></div><div class="note">按日统计已付成交金额，非累计金额；无成交日记 0，缺失日断开。总金额包含其他产品与私域服务，末日仅截至数据采集时刻。悬停可查看当天三项金额。</div>')
    return ''.join(parts)


def render(data, s):
    esc = lambda v: html.escape(str(v), quote=True)
    money = lambda v: '¥' + fmt(v, 2) if v is not None else '—'
    pct = lambda v: fmt(v, 2, '%')
    m = data['meta']; videos = s['videos']; byid = {r['publication_id']: r for r in s['eligible']}
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>视频号复盘</title><style>' + (Path(__file__).with_name('dashboard.css')).read_text(encoding='utf-8') + '</style><main class="wrap">']
    def add(text): parts.append(text)
    def note(text): add('<div class="note">' + text + '</div>')
    def highlight(value): return '<strong class="key">'+str(value)+'</strong>'
    def bar(value, color='blue'):
        if value is None: return '—'
        return f'<div class="meter {color}"><span style="width:{max(0,min(value,100)):.2f}%"></span></div><strong class="metric">{pct(value)}</strong>'
    colors = product_colors(data)
    def product_text(pid, value):
        return '<strong class="product-value" style="color:'+colors.get(pid,'#b9c1ce')+'">'+esc(value)+'</strong>'
    def source_badge(value):
        value = value or '未标注'
        color = 'unknown' if value == '未标注' else ('blue' if value == '关联账号' else 'purple' if value == '达人带货' else 'green' if value.startswith('私域') else 'tone'+str(int(hashlib.sha256(value.encode()).hexdigest()[:4],16)%4))
        return f'<span class="badge {color}">{esc(value)}</span>'
    def section(n, title): add(f'<h2 id="s{n}">{n}、{title}</h2>')
    def table(headers, rows, primary=()):
        if not primary:
            primary = tuple(i for i,h in enumerate(headers) if h in {
                '数值','播放合计','所发视频累计播放','处理后中位数','处理后均值',
                '店铺已付金额','视频归因金额','已付金额'})
        add('<div class="table-wrap"><table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>')
        for row in rows: add('<tr>' + ''.join('<td'+(' class="primary"' if i in primary else '')+'>'+str(c)+'</td>' for i,c in enumerate(row)) + '</tr>')
        add('</tbody></table></div>')
    def link(r, mode='full'):
        return f'<button class="tlink" data-id="{esc(r["publication_id"])}" data-mode="{mode}">{esc(r["title"])}</button>'
    def row(r, primary='views'):
        return [link(r), r['date'][5:], '图文' if r['content_type']=='image' else '视频', highlight(fmt(r.get('views'))) if primary=='views' else fmt(r.get('views')),
                highlight(pct(r.get('completion_pct'))) if primary=='completion_pct' else pct(r.get('completion_pct')), highlight(pct(r.get('three_sec_pct'))) if primary=='three_sec_pct' else pct(r.get('three_sec_pct')), fmt(r.get('watch_seconds'),2),
                fmt(r.get('follows')) if r['content_type']=='video' else '—']
    columns = ['作品','发布','类型','播放','完播率','三秒完播率','均观看 / 秒','涨粉']
    add(f'<header><h1>视频号复盘 · <em>{esc(m["from"])} → {esc(m["to"])}</em></h1><p>{esc(m["account"])} · 数据采集：{esc(m["captured_at"])} · 生成：{esc(m["generated_at"])}</p></header>')
    note(esc(m['refresh_note']))
    note(f'视频统计：{len(videos)} 条；图文 {len(s["images"])} 条只保留在播放排行和发布节奏。公开且发布满 {m["maturity_hours"]} 小时；不同发布日期的累计观察时长仍不同。')
    section('一','总览')
    kpis = [('视频统计条数',str(len(videos)),'图文另计'),('账号公开视频＋图文累计播放',fmt(m.get('account_views')),'账号范围'),
            ('当前粉丝',fmt(m.get('account_followers')),esc(m.get('account_captured_at',''))),
            ('视频累计分享',fmt(s['shares']),'当前视频样本'),
            (f'爆款视频 ≥{fmt(m["hit_threshold"])}',str(len(s['hits'])),f'产出率 {pct(ratio(len(s["hits"]),len(videos)))}'),
            ('全渠道已付',money(money_total(s['paid_orders'])),f'{len(s["paid_orders"])} 单；平台、私域分列')]
    add('<div class="kpi">'+''.join(f'<div><small>{a}</small><b>{b}</b><small>{c}</small></div>' for a,b,c in kpis)+'</div>')
    section('二','三段对比')
    add('<h3>2.1 视频指标</h3>')
    table(['区间','条数','播放','单条均播放','均完播率','均观看 / 秒','均三秒完播率','涨粉','万播放涨粉','分享'],
          [[r['from'][5:]+'–'+r['to'][5:],r['n'],fmt(r['views']),highlight(fmt(r['mean_views'])),pct(r['completion']),fmt(r['watch'],2),pct(r['three']),fmt(r['follows']),fmt(r['per10k'],1),fmt(r['shares'])] for r in s['segments']])
    add('<h3>2.2 爆款产能</h3>')
    table(['区间','视频数','爆款数','产出率','爆款播放','占该段播放'],[[r['from'][5:]+'–'+r['to'][5:],r['n'],highlight(r['hits']),bar(r['hit_rate'],'yellow'),fmt(r['hit_views']),bar(ratio(r['hit_views'],r['views']),'yellow')] for r in s['segments']])
    add('<h3>2.3 爆款清单</h3>');table(columns,[row(r) for r in sorted(s['hits'],key=lambda r:-r['views'])])
    add('<h3>2.4 去一个最高和一个最低</h3>')
    table(['区间','全量中位数','保留条数','处理后中位数','处理后均值'],[[r['from'][5:]+'–'+r['to'][5:],fmt(r['median']),r['trimmed_n'],fmt(r['trimmed_median']),fmt(r['trimmed_mean'])] for r in s['segments']])
    add('<h3>2.5 爆款集中度</h3>');note(f'{len(s["hits"])} 条爆款贡献视频播放 {pct(ratio(total(s["hits"],"views"),s["views"]))}。集中度是分布描述；重复产出能力需要继续观察。')
    section('三','播放量分布与涨粉效率')
    bins = [(0,1000,'<1000'),(1000,10000,'1000–9999'),(10000,50000,'10000–49999'),(50000,100000,'50000–99999'),(100000,float('inf'),'≥100000')]
    distribution=[]
    for low,high,label in bins:
        group=[r for r in videos if r.get('views') is not None and low<=r['views']<high]
        distribution.append([label,len(group),bar(ratio(len(group),len(videos))),fmt(sum(r['views'] for r in group)),bar(ratio(sum(r['views'] for r in group),s['views']))])
    table(['播放区间','视频数','占比','播放合计','播放占比'],distribution)
    note(f'视频万播放涨粉 {fmt(ratio(s["follows"],s["views"],10000),1)}；图文不进入分母或涨粉统计。')
    section('四','每日发布与播放')
    daily=s['daily']; n=len(daily); width=1260; step=width/max(1,n); maxn=max((r['count'] or 0 for r in daily),default=1) or 1; maxv=max((r['views'] or 0 for r in daily),default=1) or 1
    add('<div class="cadence-summary">'+''.join(f'<div><small>{label}</small><b>{value}</b></div>' for label,value in [('自然日',n),('有发布',s['active_days']),('零发布',highlight(len(s['zero_dates']))),('采集缺口',s['missing_days'])])+'</div>')
    add('<h3>逐日发布格 · 每个自然日都保留</h3><div class="calendar">')
    for r in daily:
        cls='missing' if not r['covered'] else 'zero' if r['count']==0 else 'published'
        value='待核' if not r['covered'] else str(r['count'])+' 条'
        add(f'<div class="day {cls}" title="{esc(r["date"])}"><small>{r["date"][5:]}</small><b>{value}</b><small>{"未发布" if r["count"]==0 else "视频 "+str(r["videos"])+" / 图文 "+str(r["images"]) if r["covered"] else "采集缺口"}</small></div>')
    add('</div>')
    note('零发布日期：'+('、'.join(d[5:] for d in s['zero_dates']) or '无')+'。最后一天只观察到采集时刻；采集缺口显示“待核”，不填零。')
    add('<h3>发布数量与作品累计播放</h3>')
    add('<div class="chart"><svg viewBox="0 0 1320 290" role="img" aria-label="连续自然日发布节奏">')
    points=[]
    for i,r in enumerate(daily):
        x=40+i*step; hv=(r['videos'] or 0)/maxn*180; hi=(r['images'] or 0)/maxn*180
        add(f'<rect x="{x:.1f}" y="{230-hv:.1f}" width="{step*.62:.1f}" height="{hv:.1f}" fill="#ffd400"><title>{r["date"]} 视频 {r["videos"]}，图文 {r["images"]}</title></rect>')
        add(f'<rect x="{x:.1f}" y="{230-hv-hi:.1f}" width="{step*.62:.1f}" height="{hi:.1f}" fill="#9a85ef"/>')
        if r['count']==0:add(f'<circle cx="{x:.1f}" cy="230" r="3" fill="#ff6b72"/><text x="{x:.1f}" y="220" font-size="10" fill="#ff6b72">0</text>')
        if r['views'] is not None:points.append(f'{x:.1f},{230-r["views"]/maxv*180:.1f}')
        elif points:
            add('<polyline points="'+' '.join(points)+'" fill="none" stroke="#4aa8ff" stroke-width="2"/>');points=[]
        if i%7==0 or i==n-1:add(f'<text x="{x:.1f}" y="255" font-size="11" fill="#9aa3ad">{r["date"][5:]}</text>')
    add('<polyline points="'+' '.join(points)+'" fill="none" stroke="#4aa8ff" stroke-width="2"/></svg></div>')
    note(f'黄柱＝视频，紫柱＝图文；最高日发布 {maxn} 条。蓝线＝当日发布视频截至采集时的累计播放，峰值 {fmt(maxv)}；不是当天新增播放。连续 {n} 个自然日，未发布日期已补零。发布节奏包含未满成熟期的公开作品，以免最近日期出现虚假停更；效果统计仍按成熟期筛选。')
    add('<details><summary>逐日明细（含零发布日）</summary>')
    table(['日期','全部发布','视频','图文','类型待核','所发视频累计播放'],[[r['date'],highlight('0') if r['count']==0 else fmt(r['count']),fmt(r['videos']),fmt(r['images']),fmt(r['unknown']),fmt(r['views'])] for r in daily]);add('</details>')
    section('五','视频指标与漏斗')
    complete=sum(r['views']*r['completion_pct']/100 for r in videos if r.get('views') is not None and r.get('completion_pct') is not None)
    table(['指标','数值','占视频播放'],[['播放',fmt(s['views']),'100%'],['完播人次（估算）',fmt(complete),pct(ratio(complete,s['views']))],['分享',fmt(s['shares']),pct(ratio(s['shares'],s['views']))],['涨粉',fmt(s['follows']),pct(ratio(s['follows'],s['views']))]])
    note('这些是作品汇总指标，不是同一批用户的逐级转化漏斗；不能据此认定“完播→关注”的流失原因。三秒指标采用 100%−快速划走率，未新增平台官方定义声明。')
    section('六','总播放排行');note('图文保留播放量，视频专属指标显示“不适用”，不按 0 参与统计。')
    byviews=sorted(s['eligible'],key=lambda r:r.get('views') if r.get('views') is not None else -1,reverse=True)
    add('<h3>Top 12</h3>');table(columns,[row(r) for r in byviews[:12]])
    add('<h3>Bottom 10 · 从低到高</h3>');table(columns,[row(r) for r in sorted(s['eligible'],key=lambda r:r.get('views') or 0)[:10]])
    add('<details><summary>展开全量播放排行</summary>');table(columns,[row(r) for r in byviews]);add('</details>')
    section('七','完播率与三秒完播率')
    for key,title,threshold in [('completion_pct','完播率 Top 10',800),('three_sec_pct','三秒完播率 Top 10',1500)]:
        add(f'<h3>{title} · 播放 ≥{threshold}</h3>')
        ranked=sorted([r for r in videos if (r.get('views') or 0)>=threshold and r.get(key) is not None],key=lambda r:-r[key])
        table(columns,[row(r,key) for r in ranked[:10]])
    section('八','爆款选题库')
    note('综合评分：完播率百分位 35%＋平均播放时长百分位 20%＋万播放涨粉百分位 10%＋涨粉数百分位 25%＋三秒完播率百分位 10%。仅视频；缺指标不排名。')
    table(['名次','作品','日期','综合分','完播率','平均播放时长 / 秒','万播放涨粉','涨粉','三秒完播率','播放'],[[r['综合排名'],link(r),r['date'][5:],highlight(fmt(r['综合评分'],2)),pct(r.get('completion_pct')),fmt(r.get('watch_seconds'),2),fmt(ratio(r.get('follows'),r.get('views'),10000),1),fmt(r.get('follows')),pct(r.get('three_sec_pct')),fmt(r.get('views'))] for r in s['ranked'][:25]])
    groups=defaultdict(list)
    for r in s['ranked'][:25]:groups[r.get('topic','待归类')].append(r)
    add(f'<h3>选题归类 · Top {min(25,len(s["ranked"]))} → {len(groups)} 类内容</h3>')
    note('根据完整内容的主要价值归类；每条作品计入一个主类，类内按综合评分排序。缺少全文的作品暂列“待归类”。点击标题可看全文。')
    for topic, group in sorted(groups.items(),key=lambda item:(-len(item[1]),item[1][0]['综合排名'])):
        add(f'<article class="topic-group"><div class="topic-heading"><h4>{esc(topic)}</h4><span class="badge blue">{len(group)} 条</span></div>')
        table(['排名','作品','综合分','完播率','平均播放时长 / 秒','万播放涨粉','涨粉数'],[[f'#{r["综合排名"]}',link(r),highlight(fmt(r['综合评分'],2)),pct(r.get('completion_pct')),fmt(r.get('watch_seconds'),2),fmt(ratio(r.get('follows'),r.get('views'),10000),1),highlight(fmt(r.get('follows')))] for r in group]);add('</article>')
    section('九','开头库')
    openings=sorted([r for r in videos if (r.get('three_sec_pct') or 0)>=72 and (r.get('completion_pct') or 0)>=10 and (r.get('views') or 0)>=1500],key=lambda r:-r['three_sec_pct'])
    table(['作品','三秒完播率','开头原文','约时长'],[[link(r),highlight(pct(r['three_sec_pct'])),esc(data['transcripts'][r['publication_id']].get('opening',{}).get('text','')),esc(opening_duration(data['transcripts'][r['publication_id']]))] for r in openings])
    section('十','标题库');table(columns,[row(r) for r in sorted(videos,key=lambda r:r.get('views') or 0,reverse=True)[:12]])
    note('高播放作品的标题候选，不等于标题单独贡献了播放；没有曝光及点击率时不判断标题的因果效果。')
    section('十一','分产品成交分析')
    note('后期部分成交未归因到对应视频，表中订单数和金额仅为已归因部分，不代表全部成交。全部已付成交请看小店汇总。')
    if data.get('attribution_audit', {}).get('comparisons'):
        add('<h3>早期与后期成交对比</h3>')
        table(['作品','早期点击','后期点击','早期订单 / 金额','后期订单 / 金额'],[[link(byid[r['publication_id']]) if r.get('publication_id') in byid else esc(r['title']),fmt(r['before_clicks']),fmt(r['after_clicks']),fmt(r['before_orders'])+' / '+money(r['before_amount']),fmt(r['after_orders'])+' / '+money(r['after_amount'])] for r in data['attribution_audit']['comparisons']], primary=(3,4))
        note('对照中的视频点击增加，已归因成交未同步增加；后期未归因订单不分摊给这些视频。')
    for product in s['products']:
        add('<h3>'+product_text(product['product_id'],product['label'])+'</h3>')
        video_ids={r['publication_id'] for r in videos}
        a=[a for a in data['attribution'] if a['product_id']==product['product_id'] and a['publication_id'] in video_ids]
        table(['店铺已付订单','店铺已付金额','有视频归因的订单','视频归因金额','有归因视频数','其中爆款数'],[[product['orders'],money(product['amount']),product['attributed_orders'],money(product['attributed_amount']),product['attributed_video_n'],product['hit_video_n']]])
        table(['成交视频','播放','爆款 ≥'+fmt(m['hit_threshold']),'归因订单','归因金额'],[[link(byid[x['publication_id']]),fmt(byid[x['publication_id']]['views']),'是' if byid[x['publication_id']]['views']>=m['hit_threshold'] else '否',x['orders'],highlight(money(x['amount']))] for x in a])
        if a:note(f'已取得视频归因的样本中，爆款占成交金额 {pct(ratio(product["hit_amount"],product["attributed_amount"]))}，占订单 {pct(ratio(product["hit_orders"],product["attributed_orders"]))}。本结论只覆盖可归因部分。')
        else:note('本产品没有可核实到视频的归因记录；不将店铺订单分配给某条视频。')
    section('十二','小店成交与客户明细')
    table(['产品','已付订单','单数占比','已付金额','金额占比'],[[product_text(x['product_id'],x['label']),x['orders'],bar(x['order_share']),product_text(x['product_id'],money(x['amount'])),bar(x['amount_share'],'yellow')] for x in s['products']]+[['合计',len(s['paid_orders']),pct(ratio(len(s['paid_orders']),len(s['paid_orders']))),highlight(money(money_total(s['paid_orders']))),pct(ratio(money_total(s['paid_orders']),money_total(s['paid_orders'])))]] )
    if m.get('include_customer_details',False):
        note('客户明细仅用于内部复盘；联系方式中段脱敏，地址仅显示已核实省市。Excel 保留已取得的完整信息；后台未提供的省市显示“未获取省市”。')
        table(['下单时间','买家','收件人','联系方式','省份 · 城市','商品','金额','状态','成交来源'],[[esc(o['time']),esc(o.get('buyer','')),esc(o.get('recipient','')),esc(mask_contact(o.get('phone'))),esc(region_label(o)),product_text(o['product_id'],o['product']),product_text(o['product_id'],money(o['amount'])),esc(o['status']),source_badge(o.get('channel'))] for o in s['paid_orders']])
    channels=defaultdict(list)
    for o in s['paid_orders']:channels[o.get('channel') or '未标注'].append(o)
    add('<h3>成交来源</h3>');table(['来源','已付订单','单数占比','已付金额','金额占比'],[[source_badge(k),len(v),bar(ratio(len(v),len(s['paid_orders']))),money(money_total(v)),bar(ratio(money_total(v),money_total(s['paid_orders'])),'yellow')] for k,v in channels.items()])
    add('<h3>每日成交金额</h3>')
    add(sales_chart(data, s))
    section('十三','核心结论与下一轮验证')
    for x in data['analysis']:add('<div class="find">'+esc(x)+'</div>')
    note(f'当前视频平均观看 {fmt(s["watch"],2)} 秒，爆款平均观看 {fmt(mean(s["hits"],"watch_seconds"),2)} 秒。差异不直接证明某一种文案机制有效。')
    section('十四','数据范围与待补内容')
    note('数据截至 '+esc(m['captured_at'])+'。此后的新增播放与成交尚未纳入。')
    missing=[r for r in s['eligible'] if data['transcripts'][r['publication_id']].get('status')=='missing']
    if missing:
        note('以下作品全文待补充，暂不纳入内容分类：')
        add('<div class="missing-titles">'+' · '.join(link(r) for r in missing)+'</div>')
    transcripts={k:{'full':v.get('full',''), 'reason':('图文内容，无视频逐字稿。' if v.get('status')=='not_applicable' else '全文待补充。')} for k,v in data['transcripts'].items() if k in byid}
    payload=json.dumps(transcripts,ensure_ascii=False).replace('<','\\u003c').replace('&','\\u0026')
    add('</main><aside id="side" hidden><button id="close" aria-label="关闭">×</button><h3 id="dlgtitle"></h3><p id="dlgsource"></p><div id="dlgbody"></div></aside>')
    add('<script id="transcript-data" type="application/json">'+payload+'</script>')
    add('<script>'+Path(__file__).with_name('dashboard.js').read_text(encoding='utf-8')+'</script></html>')
    return '\n'.join(parts)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.input.read_text(encoding='utf-8'));s=summarize(data)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(render(data,s),encoding='utf-8')
    a.output.with_suffix('.stats.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'videos':len(s['videos']),'images':len(s['images']),'days':len(s['daily']),'output':str(a.output)},ensure_ascii=False))


if __name__=='__main__':main()
