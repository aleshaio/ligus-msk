"""Build a self-contained PHP-hosting release; never copy local credentials."""
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--site-url', default='https://ligus-msk.ru')
a = p.parse_args()
u = urlsplit(a.site_url)
if u.scheme != 'https' or not u.hostname or u.path not in ('', '/') or u.query or u.fragment or u.username:
    p.error('--site-url must be an HTTPS origin without a path')
release = ROOT / 'release' / 'ligus-hosting'
if release.exists():
    shutil.rmtree(release)
public = release / 'public_html'
private = release / 'private' / 'contact'
env = dict(os.environ, OUTPUT_DIR=str(public), FORM_PROVIDER='smtp', BASE_PATH='', SITE_URL=a.site_url.rstrip('/'))
subprocess.run([sys.executable, str(ROOT / 'build.py')], env=env, check=True)
shutil.copytree(ROOT / 'server' / 'public', public, dirs_exist_ok=True)
private.mkdir(parents=True)
# Explicit allowlist prevents config.php / runtime / backups entering the release.
for name in ['config.example.php', 'handler.php', 'check.php', 'maintenance.php']:
    shutil.copy2(ROOT / 'server' / 'private' / 'contact' / name, private / name)
shutil.copytree(ROOT / 'server' / 'private' / 'contact' / 'vendor', private / 'vendor')
shutil.copy2(ROOT / 'docs' / 'smtp-hosting.md', release / 'README.md')
subprocess.run([sys.executable, str(ROOT / 'verify.py')], env=env, check=True)
for page in public.rglob('*.html'):
    text = page.read_text()
    assert 'formsubmit.co' not in text and 'forms.yandex.ru' not in text, page
    if 'request-form' in text:
        assert 'data-provider="smtp"' in text and 'action="/api/contact.php"' in text, page
assert not (private / 'config.php').exists()
assert not (public / 'private').exists()
archive = shutil.make_archive(str(release), 'zip', release.parent, release.name)
print(f'Hosting package: {archive}\nDocument root: {public}\nSMTP is DISABLED until config.php is supplied.')
