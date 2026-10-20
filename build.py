# -*- coding: utf-8 -*-
"""Сборка статического сайта расписания ГГПК.

Запускается в GitHub Actions: скачивает файл расписания из ВК,
разбирает его и генерирует готовые HTML-страницы в папку site/.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schedule_core as sc

VK_WIDGET = ('https://vk.com/widget_community.php?app=0&width=600&_ver=1'
             '&gid=216202806&mode=4&height=800')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site')

MSK = timezone(timedelta(hours=5))

BELLS = {
    'Ш': {
        'week': {1: [('8:30', '9:15'), ('9:20', '10:05')],
                 2: [('10:15', '11:00'), ('11:20', '12:05')],
                 3: [('12:15', '13:00'), ('13:20', '14:05')],
                 4: [('14:15', '15:00'), ('15:05', '15:50')]},
        'sat': {1: [('8:30', '9:10'), ('9:15', '9:55')],
                2: [('10:05', '10:45'), ('11:00', '11:40')],
                3: [('11:50', '12:30'), ('12:35', '13:15')]},
    },
    'М': {
        'week': {1: [('8:30', '9:15'), ('9:20', '10:05')],
                 2: [('10:30', '11:15'), ('11:20', '12:05')],
                 3: [('12:30', '13:15'), ('13:20', '14:05')],
                 4: [('14:15', '15:00'), ('15:05', '15:50')]},
        'sat': {1: [('8:30', '9:10'), ('9:15', '9:55')],
                2: [('10:20', '11:00'), ('11:05', '11:45')],
                3: [('11:50', '12:30'), ('12:35', '13:15')]},
    },
}

TRANS = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '',
    'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def slug(text):
    out = []
    for ch in (text or '').lower():
        if ch in TRANS:
            out.append(TRANS[ch])
        elif ch.isalnum() and ord(ch) < 128:
            out.append(ch)
        else:
            out.append('-')
    s = re.sub(r'-+', '-', ''.join(out)).strip('-')
    return s or 'x'


def http_get(url, timeout=90, referer=None):
    headers = {'User-Agent': UA, 'Accept-Language': 'ru-RU,ru;q=0.9'}
    if referer:
        headers['Referer'] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------- ВК ----------------
def vk_posts():
    raw = http_get(VK_WIDGET).decode('cp1251', 'ignore')
    docs = []
    for chunk in raw.split('<div class="wcommunity_post">')[1:]:
        for h, n in re.findall(r'<a class="page_doc_title" href="([^"]+)"[^>]*>([^<]*)</a>', chunk):
            docs.append({'href': h.replace('&amp;', '&'), 'name': html.unescape(n).strip()})
    return docs


def vk_download(href):
    last = None
    for attempt in range(1, 5):
        try:
            page = http_get('https://vk.com' + href).decode('cp1251', 'ignore')
            m = re.search(r'"docUrl":"(https:[^"]+)"', page)
            if not m:
                raise RuntimeError('нет прямой ссылки на файл')
            url = json.loads('"' + m.group(1) + '"')
            return http_get(url, timeout=120, referer='https://vk.com/')
        except Exception as e:
            last = e
            print('попытка %d не удалась: %s' % (attempt, e))
            time.sleep(4 * attempt)
    raise last


def fetch_main():
    docs = vk_posts()
    if not docs:
        raise RuntimeError('ВК не отдал список документов')
    cand = [d for d in docs if 'семестр' in d['name'].lower() and d['name'].lower().endswith('.pdf')]
    if not cand:
        raise RuntimeError('файл семестра не найден среди %d документов' % len(docs))
    print('файл:', cand[0]['name'])
    return vk_download(cand[0]['href'])


# ---------------- данные ----------------
def building(room):
    r = (room or '').strip()
    if not r:
        return None
    ch = r[-1].upper()
    return ch if ch in ('М', 'Ш') else None


def slots_for(pair, room, weekday):
    if pair < 1:
        return []
    b = building(room)
    if not b:
        return []
    return BELLS[b]['sat' if weekday == 5 else 'week'].get(pair, [])


def day_rows(cells, denominator):
    rows = []
    for pair in sorted(cells):
        c = cells[pair]
        subject, teacher, room = c.get('subject', ''), c.get('teacher', ''), c.get('room', '')
        if denominator and c.get('subject_den'):
            subject = c['subject_den']
            teacher = c.get('teacher_den', '')
            room = c.get('room_den', '')
        rows.append((pair, subject, room, teacher))
    return rows


# ---------------- html ----------------
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0f1720;color:#e6edf3;font:15px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:16px 14px 40px}
a{color:#5eb5f7;text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:20px;margin:6px 0 2px}
.sub{color:#8b9bab;font-size:13px;margin-bottom:14px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 18px}
.chip{background:#1b2733;border:1px solid #2a3a4a;border-radius:8px;padding:7px 11px;font-size:14px;color:#e6edf3;display:inline-block}
.chip:hover{border-color:#4a7fa8;text-decoration:none}
h2.course{font-size:14px;color:#8b9bab;font-weight:600;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.04em}
.day{margin:18px 0 6px;font-size:15px;font-weight:600;color:#cfe1f2}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #263442;border-radius:10px;background:#141e28}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:520px}
th{background:#1b2733;color:#9fb3c6;font-weight:600;text-align:left;padding:8px 10px;font-size:12px;text-transform:uppercase;letter-spacing:.03em;border-bottom:1px solid #263442}
td{padding:9px 10px;border-bottom:1px solid #1f2c38;vertical-align:top}
tr:last-child td{border-bottom:0}
td.n{color:#8b9bab;width:34px;text-align:center}
td.t{white-space:nowrap;color:#cfe1f2;width:96px;font-variant-numeric:tabular-nums}
td.s{min-width:180px}
td.r{white-space:nowrap;color:#a9c4dc;width:70px}
td.p{color:#9fb3c6;width:130px;font-size:13px}
.muted{color:#5f7285}
.switch{display:flex;gap:8px;margin:10px 0 4px}
.switch a{flex:1;text-align:center;padding:9px 10px;border-radius:9px;background:#1b2733;border:1px solid #2a3a4a;color:#cfe1f2;font-size:14px}
.switch a.on{background:#1d4a6e;border-color:#3d7fb0;color:#eaf5ff;font-weight:600}
.empty{background:#1b2733;border:1px solid #2a3a4a;border-radius:10px;padding:14px;color:#8b9bab}
input.q{width:100%;padding:11px 12px;border-radius:10px;border:1px solid #2a3a4a;background:#141e28;color:#e6edf3;font-size:15px;margin:6px 0 14px}
.foot{margin-top:26px;color:#5f7285;font-size:12px;text-align:center}
"""


def page(title, body, depth=0):
    base = '../' * depth
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>'
            '<meta name="description" content="Расписание занятий Губкинского горно-политехнического колледжа">'
            '<style>%s</style></head><body><div class="wrap">%s'
            '<div class="foot">Расписание ГГПК · данные из сообщества ВК · обновлено %s</div>'
            '</div></body></html>'
            % (html.escape(title), CSS, body, datetime.now(MSK).strftime('%d.%m %H:%M')))


def index_page(cat):
    parts = ['<h1>Расписание ГГПК</h1><div class="sub">Выберите группу</div>']
    for course in sorted(cat):
        parts.append('<h2 class="course">%s</h2><div class="chips">' % html.escape(course))
        for g in sorted(cat[course]):
            parts.append('<a class="chip" href="g/%s/n.html">%s</a>' % (slug(g), html.escape(g)))
        parts.append('</div>')
    parts.append('<h2 class="course">Преподаватели</h2>'
                 '<div class="chips"><a class="chip" href="prep.html">🔍 Найти преподавателя</a></div>')
    return page('Расписание ГГПК', ''.join(parts))


def group_page(name, course, days, den):
    label = 'Знаменатель' if den else 'Числитель'
    parts = ['<h1>%s</h1><div class="sub">%s неделя · %s</div>'
             % (html.escape(name), label.lower(), html.escape(course)),
             '<div class="switch">'
             '<a class="%s" href="n.html">Числитель</a>'
             '<a class="%s" href="z.html">Знаменатель</a></div>'
             % ('on' if not den else '', 'on' if den else '')]

    any_day = False
    for i in range(6):
        cells = days.get(i) or {}
        rows = day_rows(cells, den)
        if not rows:
            continue
        any_day = True
        parts.append('<div class="day">%s</div>' % sc.DAYS[i].capitalize())
        parts.append('<div class="tw"><table><thead><tr><th>№</th><th>Время</th>'
                     '<th>Пара</th><th>Ауд.</th><th>Преподаватель</th></tr></thead><tbody>')
        if 1 not in [r[0] for r in rows]:
            parts.append('<tr><td class="n">1</td><td class="t muted">—</td><td class="s muted">—</td>'
                         '<td class="r muted">—</td><td class="p muted">—</td></tr>')
        for pair, subject, room, teacher in rows:
            slots = slots_for(pair, room, i)
            t = '<br>'.join('%s–%s' % s for s in slots) if slots else '<span class="muted">—</span>'
            parts.append('<tr><td class="n">%d</td><td class="t">%s</td><td class="s">%s</td>'
                         '<td class="r">%s</td><td class="p">%s</td></tr>'
                         % (pair, t, html.escape(subject or '—'), html.escape(room or '—'),
                            html.escape(teacher or '—')))
        parts.append('</tbody></table></div>')
    if not any_day:
        parts.append('<div class="empty">На эту неделю пар нет.</div>')
    parts.append('<p><a href="../index.html">← все группы</a></p>')
    return page('%s · %s' % (name, label), ''.join(parts), depth=2)


def teachers_index(entries):
    """entries: {name: [(group, day, pair, subject, room), ...]}"""
    items = sorted(entries)
    rows = []
    for t in items:
        rows.append('<a class="chip" data-n="%s" href="p/%s.html">%s</a>'
                    % (html.escape(t.lower()), slug(t), html.escape(t)))
    parts = ['<h1>Преподаватели</h1><div class="sub">Всего: %d</div>' % len(items),
             '<input class="q" id="q" placeholder="Фамилия, например Коваль" autocomplete="off">',
             '<div class="chips" id="list">%s</div>' % ''.join(rows),
             '<p><a href="index.html">← все группы</a></p>',
             '<script>'
             'var q=document.getElementById("q"),l=document.getElementById("list");'
             'q.addEventListener("input",function(){var v=q.value.toLowerCase().trim();'
             'Array.prototype.forEach.call(l.children,function(a){'
             'a.style.display=a.dataset.n.indexOf(v)>-1?"":"none";});});'
             '</script>']
    return page('Преподаватели', ''.join(parts))


def prep_page(name, entries):
    by_day = {}
    for g, d, pair, subject, room in entries:
        by_day.setdefault(d, []).append((pair, g, subject, room))
    parts = ['<h1>%s</h1><div class="sub">%d пар в неделю (числитель и знаменатель)</div>'
             % (html.escape(name), len(entries))]
    for d in sorted(by_day):
        parts.append('<div class="day">%s</div>' % sc.DAYS[d].capitalize())
        parts.append('<div class="tw"><table><thead><tr><th>№</th><th>Время</th><th>Группа</th>'
                     '<th>Пара</th><th>Ауд.</th></tr></thead><tbody>')
        for pair, g, subject, room in sorted(by_day[d], key=lambda x: (x[0], x[1])):
            slots = slots_for(pair, room, d)
            t = '<br>'.join('%s–%s' % s for s in slots) if slots else '<span class="muted">—</span>'
            parts.append('<tr><td class="n">%d</td><td class="t">%s</td><td class="r">%s</td>'
                         '<td class="s">%s</td><td class="r">%s</td></tr>'
                         % (pair, t, html.escape(g), html.escape(subject or '—'),
                            html.escape(room or '—')))
        parts.append('</tbody></table></div>')
    parts.append('<p><a href="../prep.html">← поиск</a></p>')
    return page(name, ''.join(parts), depth=1)


# ---------------- сборка ----------------
def collect_teachers(cat):
    names = {}
    for course in cat:
        for g in cat[course]:
            for d, cells in cat[course][g].items():
                for pair, c in cells.items():
                    t = (c.get('teacher') or '').strip()
                    if t:
                        names.setdefault(t, []).append(
                            (g, d, pair, c.get('subject') or '', c.get('room') or ''))
    return names


def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def build(pdf_bytes):
    tmp = os.path.join(OUT, '_main.pdf')
    os.makedirs(OUT, exist_ok=True)
    with open(tmp, 'wb') as f:
        f.write(pdf_bytes)
    cat = sc.parse_main(tmp)
    os.remove(tmp)

    total = sum(len(v) for v in cat.values())
    print('групп: %d' % total)

    write('index.html', index_page(cat))
    for course in cat:
        for g in cat[course]:
            for den, kind in ((False, 'n'), (True, 'z')):
                write('g/%s/%s.html' % (slug(g), kind), group_page(g, course, cat[course][g], den))

    t = collect_teachers(cat)
    print('преподавателей: %d' % len(t))
    write('prep.html', teachers_index(t))
    for name, entries in t.items():
        write('p/%s.html' % slug(name), prep_page(name, entries))

    write('robots.txt', 'User-agent: *\nAllow: /\n')
    return total


def main():
    data = fetch_main()
    print('скачано: %d КБ' % (len(data) // 1024))
    n = build(data)
    print('готово: %d групп, %d страниц' % (n, n * 2 + 1))


if __name__ == '__main__':
    main()
