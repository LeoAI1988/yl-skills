"""Regression coverage for cohort isolation, attribution and HTML privacy."""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dashboard',ROOT/'yl-channels-analytics/scripts/dashboard.py')
dash=importlib.util.module_from_spec(spec);spec.loader.exec_module(dash)

def fixture():
    posts=[dict(publication_id='v1',title='Same title',date='2026-01-01',public=True,mature=True,content_type='video',views=200,completion_pct=50,three_sec_pct=80,watch_seconds=20,duration_seconds=40,follows=10,shares=2),
           dict(publication_id='i1',title='Image',date='2026-01-01',public=True,mature=True,content_type='image',views=9999,completion_pct=None,three_sec_pct=None,watch_seconds=None,duration_seconds=None,follows=None,shares=None),
           dict(publication_id='v2',title='Same title',date='2026-01-03',public=True,mature=False,content_type='video',views=2,completion_pct=None,three_sec_pct=None,watch_seconds=None,duration_seconds=20,follows=0,shares=0)]
    orders=[dict(order_id='order1',product_id='premium',product='Premium',time='2026-01-01',amount=90,paid=True,status='paid',buyer='Customer name',phone='1234567890',address='Customer address'),dict(order_id='order2',product_id='entry',product='Entry',time='2026-01-01',amount=9.9,paid=True,status='paid')]
    return dict(meta=dict(account='Demo',**{'from':'2026-01-01','to':'2026-01-03'},captured_at='2026-01-03T00:00:00Z',generated_at='2026-01-03T01:00:00Z',refresh_note='Fixture only',attribution_note='Observed',maturity_hours=48,hit_threshold=100,segments=[['2026-01-01','2026-01-03']]),posts=posts,orders=orders,products=[dict(product_id='premium',label='Premium includes discounted orders'),dict(product_id='entry',label='Entry')],attribution=[dict(product_id='premium',publication_id='v1',orders=1,amount=90,evidence='Observed')],transcripts={'v1':dict(status='raw_asr',full='First text </script><unsafe>',opening={'text':'First','label':'0–2 seconds'}),'i1':dict(status='not_applicable',reason='Image'),'v2':dict(status='raw_asr',full='Other text')},analysis=[],coverage=[])

class DashboardTests(unittest.TestCase):
    def test_image_does_not_change_video_statistics_or_rank(self):
        d=fixture();s=dash.summarize(d)
        self.assertEqual(s['views'],200);self.assertEqual(s['segments'][0]['completion'],50)
        self.assertEqual([x['publication_id'] for x in s['ranked']],['v1'])
        d['posts'][1]['views']=99999999
        self.assertEqual(dash.summarize(d)['ranked'],s['ranked'])
    def test_calendar_includes_recent_posts_and_zero_days(self):
        s=dash.summarize(fixture());self.assertEqual(len(s['daily']),3)
        self.assertEqual(s['daily'][1]['videos'],0);self.assertEqual(s['daily'][2]['videos'],1)
        self.assertEqual(len(s['videos']),1)
    def test_discount_and_product_attribution_remain_separate(self):
        s=dash.summarize(fixture());p,q=s['products']
        self.assertEqual((p['amount'],p['attributed_orders'],p['hit_video_n']),(90,1,1))
        self.assertEqual((q['amount'],q['attributed_orders']),(9.9,0))
        self.assertEqual(dash.money_total([{'amount':9.9}]*3),29.7)
    def test_html_privacy_and_script_escaping(self):
        d=fixture();page=dash.render(d,dash.summarize(d))
        self.assertNotIn('Customer name',page);self.assertNotIn('1234567890',page)
        d['meta']['include_customer_details']=True;page=dash.render(d,dash.summarize(d))
        self.assertIn('Customer name',page);self.assertNotIn('Customer address',page)
        self.assertIn('未获取省市',page)
        self.assertNotIn('1234567890',page);self.assertIn(dash.mask_contact('1234567890'),page)
        self.assertNotIn('</script><unsafe>',page)
    def test_opening_does_not_claim_exact_five_seconds(self):
        o=dash.opening([dict(start=0,end=8,text='Long segment')],'')
        self.assertFalse(o['exact']);self.assertEqual(o['end'],8)
        self.assertIsNone(dash.opening([],'No timestamps')['end'])
    def test_calendar_gap_is_not_zero_and_zero_is_visible(self):
        d=fixture();s=dash.summarize(d)
        self.assertEqual(s['zero_dates'],['2026-01-02'])
        self.assertIn('day zero',dash.render(d,s))
        d['meta']['calendar_missing_dates']=['2026-01-02']
        s=dash.summarize(d);self.assertEqual(s['zero_dates'],[])
        self.assertIsNone(s['daily'][1]['count']);self.assertEqual(s['missing_days'],1)
    def test_product_percentages_recompute_and_region_is_structured(self):
        d=fixture();s=dash.summarize(d)
        self.assertEqual(s['products'][0]['order_share'],50)
        self.assertAlmostEqual(sum(r['amount_share'] for r in s['products']),100)
        d['orders'][0]['amount']=9.9
        self.assertEqual(dash.summarize(d)['products'][0]['amount_share'],50)
        self.assertEqual(dash.region_label({'province':'广东省','city':'深圳市','address':'secret street'}),'广东省 · 深圳市')
        self.assertEqual(dash.region_label({'address':'***'}),'未获取省市')
    def test_rejects_duplicate_identity_and_image_video_metrics(self):
        d=fixture();d['posts'].append(copy.deepcopy(d['posts'][0]))
        with self.assertRaises(ValueError):dash.summarize(d)

    def test_sales_daily_products_total_zero_and_gap(self):
        d=fixture();d['orders'].append(dict(order_id='extra',product_id='other',time='2026-01-02',paid=True,amount=20))
        s=dash.summarize(d);ids,rows=dash.sales_series(d,s)
        self.assertEqual(ids,['premium','entry'])
        self.assertEqual(rows[0]['total'],99.9)
        self.assertEqual(rows[1]['total'],20)
        self.assertEqual(sum(rows[1]['products'].values()),0)
        self.assertEqual(rows[2]['total'],0)
        d['meta']['orders_missing_dates']=['2026-01-03']
        self.assertIsNone(dash.sales_series(d,s)[1][2]['total'])
        page=dash.render(d,s)
        self.assertNotIn('订单时间分布',page)
        self.assertEqual(page.count('data-series='),3)

    def test_html_drops_internal_evidence_but_keeps_full_text(self):
        d=fixture();d['transcripts']['v1'].update(source_path='private/path',source_sha256='secret-hash',match_evidence='internal-match')
        d['coverage']=[dict(item='internal-coverage',status='partial',reason='internal-log')]
        page=dash.render(d,dash.summarize(d))
        for value in ['private/path','secret-hash','internal-match','internal-log','稿件状态','商品对应证据']:
            self.assertNotIn(value,page)
        self.assertIn('First text',page)
        self.assertIn('后期部分成交未归因',page)
        self.assertNotIn("dataset.mode==='head'",page)

    def test_watch_time_changes_score_and_missing_is_not_zero(self):
        d=fixture();a=d['posts'][0];b=copy.deepcopy(a);b.update(publication_id='v3',watch_seconds=40)
        d['posts'].append(b)
        rows=dash.summarize(d)['ranked']
        self.assertEqual(rows[0]['publication_id'],'v3')
        self.assertEqual(rows[0]['综合评分'],20)
        b['watch_seconds']=None
        self.assertEqual(len(dash.summarize(d)['ranked']),1)
        d=fixture();d['posts'][1]['completion_pct']=0
        with self.assertRaises(ValueError):dash.summarize(d)

if __name__=='__main__':unittest.main(verbosity=2)
