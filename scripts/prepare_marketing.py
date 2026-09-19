"""Validate and export offline advertising drafts. Does not access an ad account."""
import csv
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'marketing'
plan = json.loads((FOLDER / 'direct-plan.json').read_text())


def landing(path, tracked=False):
    url = urlsplit(plan['origin'] + path)
    page = ROOT / 'dist' / url.path.lstrip('/') / 'index.html'
    assert page.exists(), path
    if url.fragment:
        assert f'id="{url.fragment}"' in page.read_text(), path
    return urlunsplit((url.scheme, url.netloc, url.path,
                      plan['utm_template'] if tracked else url.query, url.fragment))


def length(text, limit, word_limit):
    assert len(text) <= limit, (len(text), limit, text)
    assert all(len(word) <= word_limit for word in text.split()), text


for link in plan['sitelinks']:
    length(link['title'], 30, 23)
    length(link['description'], 60, 23)
    landing(link['path'])
assert sum(len(s['title']) for s in plan['sitelinks']) <= 66
assert sum(len(s) for s in plan['callouts']) <= 76
assert all(len(s) <= 25 for s in plan['callouts'])
for group in plan['groups']:
    assert 1 <= len(group['headlines']) <= 7
    assert 1 <= len(group['texts']) <= 3
    for text in group['headlines']:length(text, 56, 22)
    for text in group['texts']:
        length(text, 81, 23)
        assert len(re.findall(r'[^\w\s]', text)) <= 15, text
    assert len(landing(group['landing'], True)) <= 1024
    assert len(group['keywords']) == len(set(group['keywords']))

export = FOLDER / 'direct-import'
export.mkdir(exist_ok=True)
# Documented tab-delimited UTF-8 format. Import into a paused EPK and inspect
# the preview in Commander; account-level budgets/statuses are never serialized.
fields = ['Доп. объявление группы', 'Название группы', 'Номер группы',
          'Фраза (с минус-словами)', 'Заголовок 1', 'Заголовок 2', 'Заголовок 3',
          'Заголовок 4', 'Текст 1', 'Текст 2', 'Текст 3', 'Ссылка',
          'Минус-фразы на кампанию', 'Заголовки быстрых ссылок',
          'Описания быстрых ссылок', 'Адреса быстрых ссылок', 'Уточнения']
for campaign in plan['campaigns']:
    assert campaign['enabled'] is False and campaign['weekly_budget_rub'] is None
    with (export / (campaign['id'] + '.tsv')).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for i, group in enumerate(plan['groups'], 1):
            if group['campaign'] != campaign['id']:continue
            for phrase in group['keywords']:
                row = {'Доп. объявление группы': '-', 'Название группы': group['name'],
                       'Номер группы': i, 'Фраза (с минус-словами)': phrase,
                       'Ссылка': landing(group['landing'], True),
                       'Минус-фразы на кампанию': ', '.join(plan['negative_keywords']),
                       'Заголовки быстрых ссылок': '||'.join(s['title'] for s in plan['sitelinks']),
                       'Описания быстрых ссылок': '||'.join(s['description'] for s in plan['sitelinks']),
                       'Адреса быстрых ссылок': '||'.join(landing(s['path'], True) for s in plan['sitelinks']),
                       'Уточнения': '||'.join(plan['callouts'])}
                row.update({f'Заголовок {n}': text for n,text in enumerate(group['headlines'], 1)})
                row.update({f'Текст {n}': text for n,text in enumerate(group['texts'], 1)})
                writer.writerow(row)

with (FOLDER/'seo-map.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer=csv.writer(f,lineterminator='\n');writer.writerow(['URL','Title','Description','H1/раздел'])
    for slug,data in json.loads((FOLDER/'seo-pages.json').read_text()).items():
        writer.writerow([plan['origin']+'/'+(slug+'/' if slug else ''),data['title'],data['description'],data['label']])

preview = ['# Объявления Лигус — подготовлено к подключению',
           '\nСтатус: офлайн-черновики. Не загружены в кабинет, бюджет не задан, показы не запущены.',
           '\nСемантика — стартовые гипотезы. Частотность и цены клика не проверялись в Вордстате/кабинете.']
for group in plan['groups']:
    preview.extend([f'\n## {group["name"]}', f'\nСтраница: {landing(group["landing"])}',
                    '\nЗаголовки:\n'+''.join(f'- {s}\n' for s in group['headlines']),
                    '\nТексты:\n'+''.join(f'- {s}\n' for s in group['texts']),
                    '\nФразы:\n'+''.join(f'- {s}\n' for s in group['keywords'])])
(FOLDER/'ads-preview.md').write_text('\n'.join(preview).rstrip()+'\n')
report=dict(campaigns=len(plan['campaigns']), groups=len(plan['groups']),
            phrases=sum(len(g['keywords']) for g in plan['groups']),
            headlines=sum(len(g['headlines']) for g in plan['groups']),
            texts=sum(len(g['texts']) for g in plan['groups']),
            status='offline_draft_not_uploaded', checks='lengths, local targets, anchors, URL tags')
(FOLDER/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
(ROOT/'release').mkdir(exist_ok=True)
shutil.make_archive(str(ROOT/'release'/'ligus-marketing'), 'zip', ROOT, 'marketing')
