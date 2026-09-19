"""Search metadata and explicit launch controls for the static builder."""
import html
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent
PAGES = json.loads((ROOT / 'marketing' / 'seo-pages.json').read_text())
EXCLUDED = {'404', 'thanks', 'privacy', 'request', 'projects', 'documents'}


class SearchConfig:
    def __init__(self, site, site_url):
        self.origin = site['domain'].rstrip('/')
        self.enabled = os.environ.get('INDEXING_ENABLED', '0') == '1'
        self.counter = os.environ.get('METRICA_ID', '').strip()
        self.verification = os.environ.get('YANDEX_VERIFICATION', '').strip()
        if self.counter and (not self.counter.isdigit() or int(self.counter) <= 0):
            raise ValueError('METRICA_ID must be a positive numeric counter ID')
        if (self.enabled or self.counter) and (site_url != self.origin or os.environ.get('BASE_PATH', '').strip('/')):
            raise ValueError('Indexing and analytics may only be enabled on the primary domain')
        if urlsplit(self.origin).scheme != 'https':
            raise ValueError('Canonical domain must use HTTPS')
        self.site = site

    def url(self, slug=''):
        return self.origin + '/' + (slug.strip('/') + '/' if slug else '')

    def robots(self, slug):
        return 'index,follow,max-image-preview:large' if self.enabled and slug in PAGES else 'noindex,follow'

    def extra_meta(self):
        tag = f'<meta name="metrica-id" content="{self.counter}">'
        if self.verification:
            tag += f'<meta name="yandex-verification" content="{html.escape(self.verification, quote=True)}">'
        return tag

    def graph(self, slug, title, description, existing=None):
        org_id = self.url() + '#organization'
        nodes = [
            {'@type': 'Organization', '@id': org_id, 'name': self.site['name'],
             'url': self.url(), 'logo': self.origin + '/assets/ligus-logo.svg',
             'telephone': self.site['phoneHref'], 'email': self.site['email'],
             'areaServed': self.site['areaServed']},
            {'@type': 'WebSite', '@id': self.url() + '#website', 'url': self.url(),
             'name': self.site['name'], 'inLanguage': 'ru-RU', 'publisher': {'@id': org_id}},
            {'@type': 'WebPage', '@id': self.url(slug) + '#page', 'url': self.url(slug),
             'name': title, 'description': description, 'inLanguage': 'ru-RU',
             'isPartOf': {'@id': self.url() + '#website'}}
        ]
        if slug and slug != '404':
            crumbs = [('Главная', self.url())]
            if slug.startswith('production/'):
                crumbs.append(('Продукция', self.url('production')))
            crumbs.append((PAGES.get(slug, {}).get('label', title.split(' | ')[0]), self.url(slug)))
            nodes.append({'@type': 'BreadcrumbList', 'itemListElement': [
                {'@type': 'ListItem', 'position': i, 'name': name, 'item': url}
                for i, (name, url) in enumerate(crumbs, 1)]})
        if existing and existing.get('@type') != 'Organization':
            nodes.append({k: v for k, v in existing.items() if k != '@context'})
        if slug.startswith('production/'):
            nodes.append({'@type': 'Service', 'name': PAGES[slug]['label'],
                          'serviceType': 'Подбор и поставка оборудования для организаций',
                          'provider': {'@id': org_id}, 'url': self.url(slug),
                          'areaServed': self.site['areaServed']})
        return {'@context': 'https://schema.org', '@graph': nodes}

    def write_discovery(self, out):
        # Let crawlers read noindex on preview/utility pages; never block those HTML pages.
        robots = 'User-agent: *\nAllow: /\nDisallow: /api/\n'
        if self.enabled:
            robots += '\nSitemap: ' + self.origin + '/sitemap.xml\n'
        (out / 'robots.txt').write_text(robots, encoding='utf-8')
        urls = [self.url(slug) for slug in PAGES] if self.enabled else []
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        xml += ''.join(f'<url><loc>{html.escape(url)}</loc></url>\n' for url in urls)
        (out / 'sitemap.xml').write_text(xml + '</urlset>\n', encoding='utf-8')
