"""Check information preservation and lexical boundaries using a real font."""
import argparse,re,sys
from pathlib import Path
def main():
 a=argparse.ArgumentParser();a.add_argument('--font',required=True);a.add_argument('--tokenizer-dir');args=a.parse_args()
 if args.tokenizer_dir:sys.path.insert(0,args.tokenizer_dir)
 from paginate import pages
 from PIL import ImageFont
 norm=lambda t:re.sub(r'[^\u4e00-\u9fffa-z0-9]','',t.lower())
 text='现在把工具用上，开始使用完整资料，并整理为可复用的数字资产。Codex与WorkBuddy可以协作，准确率示例是99.9%。'
 protected=['用上','使用','数字资产','Codex','WorkBuddy','99.9%']
 out=pages(text,args.font,protected=protected,max_width=940)
 assert ''.join(norm(p['text']) for p in out)==norm(text),'Paging deleted or duplicated source characters'
 font=ImageFont.truetype(args.font,124)
 assert all(font.getlength(p['text'])*.946<=940 for p in out),'Fixed-size line exceeds safe width'
 raw=norm(text);bounds={p['end'] for p in out[:-1]}
 for word in protected:
  w=norm(word);start=raw.index(w);assert not any(start<b<start+len(w) for b in bounds),'An indivisible term was split: '+word
 assert any('99.9%' in p['text'] for p in out),'Decimal or percent formatting was lost'
 print('PASS: source characters, real fixed-size width, protected words, decimal and percent formatting')
if __name__=='__main__':main()
