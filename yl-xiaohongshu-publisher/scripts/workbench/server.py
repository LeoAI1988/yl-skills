"""Loopback-only workbench. No third-party Python packages required."""
import argparse
import csv
import io
import json
import mimetypes
import re
import secrets
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from engine import Store, times, matching_tags
from runner import Runner

WEB=Path(__file__).parent/'web'

def serve(config):
    store=Store(config);runner=Runner(store);token=secrets.token_urlsafe(32)
    port=int(config.get('port',18767));origin=f'http://127.0.0.1:{port}'
    scans={};scan_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data,kind='application/json; charset=utf-8'):
            if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False).encode()
            if isinstance(data,str):data=data.encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; media-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(data)
        def host_ok(self):return self.headers.get('Host')==f'127.0.0.1:{port}'
        def do_GET(self):
            if not self.host_ok():return self.send(403,{'error':'仅接受本机访问'})
            u=urlparse(self.path);q=parse_qs(u.query)
            try:
                if u.path=='/api/health':return self.send(200,dict(app='yl-xiaohongshu-workbench',**runner.health()))
                if u.path=='/api/state':return self.send(200,dict(**store.snapshot(),executor=runner.health(),scans=scans))
                if u.path=='/api/times':
                    pref=store.preferences()
                    return self.send(200,times(q.get('count',['1'])[0],q.get('start_time',[pref['start_time']])[0],q.get('end_time',[pref['end_time']])[0]))
                if u.path=='/api/export':
                    out=io.StringIO();w=csv.writer(out);w.writerow(['视频编号','规划发布时间','标题','正文','标签','合集','状态','视频文件','封面文件'])
                    assets={a['id']:a for a in store.get('assets')}
                    def safe(v):
                        s=str(v)
                        return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
                    for r in store.get('plan'):
                        a=assets[r['asset_id']];w.writerow([safe(x) for x in [a['id'],r['at'],a['title'],a.get('caption',''),' '.join('#'+t for t in a['tags']),a['settings']['collection'],a['state'],a['video'],a['cover']]])
                    return self.send(200,'\ufeff'+out.getvalue(),'text/csv; charset=utf-8')
                if u.path=='/media':
                    a=next(a for a in store.get('assets') if a['id']==q.get('id',[''])[0])
                    key='cover' if q.get('kind',[''])[0]=='cover' else 'video'
                    return self.media(Path(a[key]))
                if u.path=='/icon.png' and config.get('icon'):return self.media(Path(config['icon']))
                if u.path=='/':
                    return self.send(200,(WEB/'index.html').read_text(encoding='utf-8').replace('__CSRF__',token),'text/html; charset=utf-8')
                if u.path in ['/app.js','/style.css']:
                    p=WEB/u.path.lstrip('/');return self.send(200,p.read_bytes(),('text/javascript' if p.suffix=='.js' else 'text/css')+'; charset=utf-8')
                self.send(404,{'error':'未找到'})
            except (KeyError,StopIteration,FileNotFoundError):self.send(404,{'error':'文件不存在'})
            except (ConnectionError,BrokenPipeError):pass
            except Exception as e:self.send(400,{'error':str(e)})
        def media(self,p):
            if not p.is_file():return self.send(404,{'error':'文件不存在'})
            size=p.stat().st_size;start=0;end=size-1;status=200
            if self.headers.get('Range'):
                m=re.fullmatch(r'bytes=(\d*)-(\d*)',self.headers['Range'])
                if not m or not any(m.groups()):return self.send(416,{'error':'范围无效'})
                start=int(m[1]) if m[1] else max(0,size-int(m[2]));end=min(size-1,int(m[2])) if m[1] and m[2] else size-1
                if start>end or start>=size:return self.send(416,{'error':'范围无效'})
                status=206
            self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(str(p))[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
            self.send_header('X-Content-Type-Options','nosniff')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with p.open('rb') as f:
                    f.seek(start);left=end-start+1
                    while left:
                        chunk=f.read(min(left,256*1024))
                        if not chunk:break
                        self.wfile.write(chunk);left-=len(chunk)
            except (ConnectionError,BrokenPipeError):pass
        def do_POST(self):
            if not self.host_ok() or self.headers.get('Origin')!=origin or self.headers.get('X-CSRF-Token')!=token:
                return self.send(403,{'error':'请从本机工作台操作'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<2_000_000:raise ValueError('请求大小不正确')
                body=json.loads(self.rfile.read(length));path=urlparse(self.path).path;result={}
                if path=='/api/scan':
                    folder=body['folder'].strip()
                    with scan_lock:
                        if any(s['state']=='running' for s in scans.values()):raise ValueError('正在扫描，请等当前扫描结束')
                        sid=secrets.token_hex(6);scans[sid]={'state':'running','folder':folder}
                    def run_scan():
                        try:scans[sid].update(state='done',**store.scan(folder))
                        except Exception as e:scans[sid].update(state='failed',error=str(e))
                    threading.Thread(target=run_scan,daemon=True).start();result={'id':sid}
                elif path=='/api/folder/remove':store.remove_folder(body['folder'])
                elif path=='/api/select':store.select(body['ids'],body['selected'])
                elif path=='/api/account':result=store.set_account(body['account'])
                elif path=='/api/edit':result=store.edit(body['id'],body['patch'])
                elif path=='/api/tags':
                    a=next(a for a in store.get('assets') if a['id']==body['id']);result={'tags':matching_tags(body.get('title',a['title']),body.get('caption',a.get('caption','')),config.get('tag_pool',[]),'stable')}
                elif path=='/api/arrange':result=store.arrange(body['ids'],body['date'],body['count'],body.get('start_time'),body.get('end_time'))
                elif path=='/api/plan':store.update_plan(body['rows'],body['revision'])
                elif path=='/api/plan/replace':store.replace_video(body['slot'],body['asset_id'],body['revision'])
                elif path=='/api/plan/move':store.move_video(body['source'],body['target'],body['placement'],body['revision'])
                elif path=='/api/publish':
                    if body.get('confirmed') is not True:raise ValueError('请先确认仅准备本条表单，最后由你到小红书提交')
                    result=runner.start(body['slots'],body.get('model'),body.get('reasoning_effort'),expected_revision=body.get('revision'))
                elif path=='/api/stop':runner.stop()
                elif path=='/api/verify':result=runner.verify(body['id'])
                elif path=='/api/release':result=runner.release(body['id'])
                else:return self.send(404,{'error':'未知操作'})
                self.send(200,{'ok':True,'result':result})
            except Exception as e:self.send(400,{'error':str(e)})
    http=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    http.daemon_threads=True;http.serve_forever()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    serve(json.loads(Path(args.config).read_text(encoding='utf-8-sig')))
