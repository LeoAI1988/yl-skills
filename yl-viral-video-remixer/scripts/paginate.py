"""Measured Chinese subtitle paging; requires external Pillow and jieba.

Tokenization is a drafting aid. Read back every page boundary before rendering.
The caller maps resulting normalized offsets to its verified source timestamps.
"""
import re
from PIL import ImageFont
_TOKENIZER=None

def pages(text,font_file,size=124,scale_x=.946,max_width=960,protected=(),tokenizer=None):
 global _TOKENIZER
 if tokenizer is None:
  import jieba
  jieba.setLogLevel(50)
  if _TOKENIZER is None:_TOKENIZER=jieba.Tokenizer()
  tokenizer=_TOKENIZER
 for word in ['用上','用起来','使用','远远','想方设法',*protected]:tokenizer.add_word(word,freq=1000000)
 font=ImageFont.truetype(str(font_file),size)
 result=[];offset=0
 punctuation=r'[，。！？、：；,!?:;]|(?<!\d)\.|\.(?!\d)'
 for phrase in re.split('('+punctuation+')',text):
  if not phrase:continue
  if re.fullmatch(punctuation,phrase):
   continue
  # Match explicit terms before jieba so multiword English names keep spaces.
  terms=sorted(set(protected),key=len,reverse=True)
  pattern='('+'|'.join([*(re.escape(t) for t in terms),r'\d+(?:\.\d+)?[%％]?'])+')'
  tokens=[]
  for part in re.split(pattern,phrase):
   if not part:continue
   if part in terms or re.fullmatch(r'\d+(?:\.\d+)?[%％]?',part):tokens.append(part)
   else:tokens.extend(tokenizer.cut(part,HMM=False))
  tokens=[t for t in tokens if t.strip()]
  for token in tokens:
   if font.getlength(token)*scale_x>max_width:raise ValueError('Indivisible token exceeds fixed width: '+token)
  # Prefer fewer pages, then balance them and avoid one-character tail pages.
  n=len(tokens);dp=[None]*(n+1);dp[0]=(0,[])
  weak_end={'的','地','得','把','被','与','和','跟','对','给','让','为','从','在','将','也','还','再','就','都','更','很','最','能','会','要','不','因为','所以'}
  for end in range(1,n+1):
   for begin in range(end-1,-1,-1):
    text_page=''.join(tokens[begin:end]);width=font.getlength(text_page)*scale_x
    if width>max_width:break
    if dp[begin] is None:continue
    count=len(re.sub(r'[^\u4e00-\u9fffa-z0-9]','',text_page.lower()))
    cost=10000+100*(1-width/max_width)**2+(500 if count==1 and n>1 else 0)
    if end<n and tokens[end-1] in weak_end:cost+=45
    if begin>0 and tokens[begin] in {'的','地','得','了','着','过'}:cost+=100
    candidate=(dp[begin][0]+cost,dp[begin][1]+[text_page])
    if dp[end] is None or candidate[0]<dp[end][0]:dp[end]=candidate
  if dp[n] is None:raise ValueError('No fixed-size pagination found')
  for text_page in dp[n][1]:
   count=len(re.sub(r'[^\u4e00-\u9fffa-z0-9]','',text_page.lower()));result.append({'text':text_page,'start':offset,'end':offset+count});offset+=count
 return result
