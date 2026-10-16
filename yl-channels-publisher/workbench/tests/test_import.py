"""Isolated evidence ingestion tests; generated fixtures, no platform calls."""
import unittest,importlib.util,tempfile,json,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
sys.dont_write_bytecode=True
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/import-history.py'
spec=importlib.util.spec_from_file_location('channels_import',SCRIPT);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config={'account':'Test Account','dashboardScript':str(SCRIPT.parents[3]/'yl-channels-analytics/scripts/dashboard.py')}
        self.at=datetime.now(timezone.utc)-timedelta(minutes=5)
    def capture(self,offset=0,rows=None,extra=None):
        at=(self.at+timedelta(seconds=offset)).isoformat();job=self.root/('job'+str(offset));job.mkdir()
        rows=rows if rows is not None else [{'objectId':'9007199254740993123','createTime':int((self.at-timedelta(days=5)).timestamp()),'mediaType':4,'visibleType':3,'shortTitle':'Synthetic test title','readCount':100,'fullPlayRate':0.4,'fastFlipRate':0.2,'followCount':2}]
        doc={'account':'Test Account','captured_at':at,'total':len(rows),'posts':rows};doc.update(extra or {})
        (job/'posts.json').write_text(json.dumps(doc),encoding='utf8')
        result={'kind':'capture','account':'Test Account','capturedAt':at,'status':'complete','files':{'posts':'posts.json'},'coverage':[{'layer':'posts','status':'complete','checkedCount':len(rows),'expectedCount':len(rows),'reason':'Synthetic fully traversed fixture'}],'evidence':{'source':'test fixture','readOnly':True,'completedAt':at,'paginationExhausted':True,'includesHidden':True}}
        (job/'result.json').write_text(json.dumps(result),encoding='utf8')
        return mod.archive_capture(self.root,self.config,job)
    def test_empty(self):
        data,review,manifest=mod.build(self.root,self.config,[])
        self.assertEqual(data['posts'],[]);self.assertIsNone(data['summary']['latestCapturedAt'])
    def test_hidden_capture_and_render(self):
        cid=self.capture();data,review,_=mod.build(self.root,self.config,[cid]);p=data['posts'][0]
        self.assertEqual(p['id'],'9007199254740993123');self.assertEqual(p['visibility'],'hidden');self.assertIsNone(data['summary']['paidOrders'])
        self.assertIsNone(data['summary']['accountDailyViews']);self.assertIsNone(p['metrics']['likes'])
        mod.render_local_review(self.config,review,data,self.root/'review.html')
        self.assertIn('十四', (self.root/'review.html').read_text(encoding='utf8'))
    def test_new_capture_retains_history_without_stale_metrics(self):
        first=self.capture();rows=[{'objectId':'9007199254740993123','createTime':int((self.at-timedelta(days=5)).timestamp()),'mediaType':4,'visibleType':1,'readCount':None}]
        second=self.capture(60,rows);data,_,_=mod.build(self.root,self.config,[first,second]);p=data['posts'][0]
        self.assertEqual(len(p['snapshots']),2);self.assertIsNone(p['metrics']['views']);self.assertEqual(p['visibility'],'public')
    def test_private_fields_rejected(self):
        with self.assertRaisesRegex(ValueError,'prohibited'):self.capture(extra={'phone':'test'})
    def test_tampered_evidence_rejected(self):
        cid=self.capture();(self.root/'data/captures'/cid/'posts.json').write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'changed'):mod.build(self.root,self.config,[cid])
if __name__=='__main__':unittest.main()
