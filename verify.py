"""Validate SEO launch mode, structured data, discovery and local navigation."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
from collections import Counter
import json, os
import xml.etree.ElementTree as ET
from seo import SearchConfig, PAGES

PROJECT = Path(__file__).parent
ROOT = Path(os.environ.get('OUTPUT_DIR', str(PROJECT / 'dist'))).resolve()
BASE_PATH = os.environ.get('BASE_PATH', '').rstrip('/')
SITE = json.loads((PROJECT / 'site.json').read_text())
SEARCH = SearchConfig(SITE, os.environ.get('SITE_URL', SITE['domain']).rstrip('/'))

class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.links=[]; self.ids=set(); self.h1=0; self.title=''; self.in_title=False
        self.meta={}; self.canonical=''; self.in_json=False; self.json_text=''; self.schemas=[]
        self.feed(path.read_text())
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.add(a['id'])
        if tag=='h1':self.h1+=1
        if tag=='title':self.in_title=True
        if tag=='meta':self.meta[a.get('name',a.get('property'))]=a.get('content','')
        if tag=='link' and a.get('rel')=='canonical':self.canonical=a.get('href','')
        if tag=='script' and a.get('type')=='application/ld+json':self.in_json=True; self.json_text=''
        if tag in ['a','link','script','img']:
            if a.get('href',a.get('src')):self.links.append(a.get('href',a.get('src')))
    def handle_endtag(self, tag):
        if tag=='title':self.in_title=False
        if tag=='script' and self.in_json:
            self.schemas.append(json.loads(self.json_text));self.in_json=False
    def handle_data(self, data):
        if self.in_title:self.title+=data
        if self.in_json:self.json_text+=data

pages={p:Page(p) for p in ROOT.rglob('index.html')}
errors=[]; count=0; indexed=[]
for path,page in pages.items():
    slug=path.parent.relative_to(ROOT).as_posix()
    if slug=='.':slug=''
    if page.h1!=1 or not page.meta.get('description'):errors.append(f'Metadata/H1: {path}')
    if page.meta.get('robots')!=SEARCH.robots(slug):errors.append(f'Index mode: {slug}')
    if page.canonical!=SEARCH.url(slug) or page.meta.get('og:url')!=page.canonical:errors.append(f'Canonical/OG URL: {slug}')
    if page.meta.get('metrica-id','')!=SEARCH.counter:errors.append(f'Counter: {slug}')
    if not page.schemas or not any(n.get('@type')=='WebPage' for n in page.schemas[0].get('@graph',[])):errors.append(f'JSON-LD: {slug}')
    if page.meta.get('robots','').startswith('index,'):indexed.append(page.canonical)
    for link in page.links:
        u=urlsplit(link)
        if u.scheme or u.netloc:continue
        route=unquote(u.path)
        if BASE_PATH and route.startswith(BASE_PATH+'/'):route=route[len(BASE_PATH):]
        target=ROOT/route.lstrip('/') if route.startswith('/') else path.parent/route
        if not u.path:target=path
        if target.is_dir():target=target/'index.html'
        count+=1
        if not target.exists():errors.append(f'{path.relative_to(ROOT)}: missing {link}')
        elif u.fragment and target in pages and u.fragment not in pages[target].ids:errors.append(f'Missing fragment: {link}')
for field,values in [('title',[p.title for p in pages.values()]),('description',[p.meta.get('description') for p in pages.values()])]:
    for text,n in Counter(values).items():
        if n>1:errors.append(f'Duplicate {field}: {text}')
sitemap=[n.text for n in ET.parse(ROOT/'sitemap.xml').findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
if sorted(indexed)!=sorted(sitemap):errors.append('Sitemap does not match indexable HTML pages')
if SEARCH.enabled and len(indexed)!=len(PAGES):errors.append('Missing indexable pages')
robots=(ROOT/'robots.txt').read_text()
if '\nDisallow: /\n' in robots:errors.append('Crawler cannot read page noindex directives')
if SEARCH.enabled and 'Sitemap: '+SEARCH.origin+'/sitemap.xml' not in robots:errors.append('Missing sitemap directive')
report={'pages':len(pages),'indexable':len(indexed),'analytics_enabled':bool(SEARCH.counter),'local_links':count,'errors':errors}
print(json.dumps(report,ensure_ascii=False,indent=2))
assert not errors
