from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
from collections import Counter
import json, os

ROOT = Path(os.environ.get('OUTPUT_DIR', str(Path(__file__).parent / 'dist'))).resolve()
BASE_PATH = os.environ.get('BASE_PATH', '').rstrip('/')
class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(); self.links=[]; self.ids=set(); self.h1=0; self.title=''; self.in_title=False; self.description=False; self.noindex=False
        self.feed(path.read_text())
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.add(a['id'])
        if tag=='h1':self.h1+=1
        if tag=='title':self.in_title=True
        if tag=='meta' and a.get('name')=='description':self.description=bool(a.get('content'))
        if tag=='meta' and a.get('name')=='robots':self.noindex=a.get('content')=='noindex,nofollow'
        if tag in ['a','link','script','img']:
            if a.get('href',a.get('src')):self.links.append(a.get('href',a.get('src')))
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
    def handle_data(self,data):
        if self.in_title:self.title+=data

pages={p:Page(p) for p in ROOT.rglob('index.html')}
errors=[]; count=0
for path,page in pages.items():
    if page.h1!=1 or not page.description or not page.noindex:errors.append(f'Metadata/H1: {path}')
    for link in page.links:
        u=urlsplit(link)
        if u.scheme or u.netloc:continue
        route = unquote(u.path)
        if BASE_PATH and route.startswith(BASE_PATH+'/'): route=route[len(BASE_PATH):]
        target=ROOT/route.lstrip('/') if route.startswith('/') else path.parent/route
        if not u.path:target=path
        if target.is_dir():target=target/'index.html'
        count+=1
        if not target.exists():errors.append(f'{path.relative_to(ROOT)}: missing {link}')
        elif u.fragment and target in pages and u.fragment not in pages[target].ids:errors.append(f'Missing fragment: {link}')
for title,n in Counter(p.title for p in pages.values()).items():
    if n>1:errors.append(f'Duplicate title: {title}')
report={'pages':len(pages),'local_links':count,'errors':errors}
print(json.dumps(report,ensure_ascii=False,indent=2))
assert not errors
