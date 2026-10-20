# -*- coding: utf-8 -*-
"""Разведка: можно ли скачать файл ВК из облака GitHub через посредников."""
import html
import json
import re
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
WIDGET = ('https://vk.com/widget_community.php?app=0&width=600&_ver=1'
          '&gid=216202806&mode=4&height=800')


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Accept-Language': 'ru-RU,ru;q=0.9'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def is_pdf(data):
    return data[:4] == b'%PDF'


raw = get(WIDGET).decode('cp1251', 'ignore')
docs = re.findall(r'<a class="page_doc_title" href="([^"]+)"[^>]*>([^<]*)</a>', raw)
main = None
for href, name in docs:
    name = html.unescape(name).strip()
    if 'семестр' in name.lower() and name.lower().endswith('.pdf'):
        main = href.replace('&amp;', '&')
        print('файл:', name)
        break
if not main:
    print('файл не найден, документов:', len(docs))
    raise SystemExit(1)

page = get('https://vk.com' + main).decode('cp1251', 'ignore')
m = re.search(r'"docUrl":"(https:[^"]+)"', page)
url = json.loads('"' + m.group(1) + '"')
print('хост файла:', url.split('/')[2])

print('\n--- напрямую ---')
try:
    data = get(url, 60)
    print('direct: %d байт, pdf=%s' % (len(data), is_pdf(data)))
except Exception as e:
    print('direct: ОШИБКА %s' % str(e)[:80])

PROXIES = [
    ('allorigins', 'https://api.allorigins.win/raw?url={q}'),
    ('codetabs', 'https://api.codetabs.com/v1/proxy?quest={q}'),
    ('corsproxy.io', 'https://corsproxy.io/?url={q}'),
    ('cors.lol', 'https://api.cors.lol/?url={q}'),
    ('corsfix', 'https://proxy.corsfix.com/?{u}'),
    ('cors.eu.org', 'https://cors.eu.org/{u}'),
    ('thingproxy', 'https://thingproxy.freeboard.io/fetch/{u}'),
    ('workers.dev', 'https://test.cors.workers.dev/?{u}'),
    ('whateverorigin', 'http://www.whateverorigin.org/get?url={q}'),
]

print('\n--- через посредников ---')
for name, tpl in PROXIES:
    target = tpl.format(q=urllib.parse.quote(url, safe=''), u=url)
    t0 = time.time()
    try:
        data = get(target, 90)
        kind = 'PDF' if is_pdf(data) else ('HTML/JSON %d' % len(data))
        print('%-16s %-12s %.1fс' % (name, kind, time.time() - t0))
    except Exception as e:
        print('%-16s ОШИБКА %s' % (name, str(e)[:60]))
