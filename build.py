# -*- coding: utf-8 -*-
"""Сборка статического сайта расписания ГГПК.

Запускается в GitHub Actions. Берёт main.pdf и файлы изменений из репозитория,
генерирует страницы и JSON с расписанием на ближайшие дни.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schedule_core as sc  # noqa: E402

VK_WIDGET = ('https://vk.com/widget_community.php?app=0&width=600&_ver=1'
             '&gid=216202806&mode=4&height=800')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
OUT = os.path.join(HERE, 'site')
MSK = timezone(timedelta(hours=5))
HORIZON = 8          # на сколько дней вперёд считаем «Сегодня/Завтра»

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


def time_html(pair, room, weekday):
    slots = slots_for(pair, room, weekday)
    if not slots:
        return '—'
    return '<br>'.join('%s–%s' % s for s in slots)


def base_rows(cells, den):
    rows = []
    for pair in sorted(cells):
        c = cells[pair]
        subject, teacher, room = c.get('subject', ''), c.get('teacher', ''), c.get('room', '')
        if den and c.get('subject_den'):
            subject = c['subject_den']
            teacher = c.get('teacher_den', '')
            room = c.get('room_den', '')
        rows.append([pair, subject, room, teacher])
    return rows


def merge_day(cells, den, changes):
    """То же, что schedule_core.build_day: базовые пары + правки."""
    rows = base_rows(cells, den)
    if changes:
        for pair, ch in changes.items():
            row = next((r for r in rows if r[0] == pair), None)
            if row is None:
                row = [pair, '', '', '']
                rows.append(row)
            if ch.get('subject') == 'НЕТ':
                row[1] = 'НЕТ ПАРЫ'
                row[2] = row[3] = ''
                continue
            if ch.get('subject'):
                row[1] = ch['subject']
            if ch.get('teacher'):
                row[3] = ch['teacher']
            if ch.get('room'):
                row[2] = ch['room']
        rows.sort(key=lambda r: r[0])
    return [r for r in rows if r[1]]


def load_changes(folder):
    """{дата: {группа: {пара: {...}}}} из файлов changes/*.pdf."""
    out = {}
    if not os.path.isdir(folder):
        return out
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith('.pdf'):
            continue
        name = f.lower()
        iso = None
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', name)
        if m:
            iso = '%s-%s-%s' % (m.group(1), m.group(2), m.group(3))
        else:
            m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', name)
            if m:
                iso = '%s-%s-%s' % (m.group(3), m.group(2), m.group(1))
        if not iso:
            continue
        try:
            out[iso] = sc.parse_changes(os.path.join(folder, f))
        except Exception as e:
            print('изменения %s не разобраны: %s' % (f, e))
    return out


def group_payload(name, course, days, changes, today):
    payload = {'name': name, 'course': course, 'today': today.isoformat(), 'days': {}, 'week': {}}
    for i in range(6):
        payload['week'].setdefault('n', []).append(
            {'day': sc.DAYS[i].capitalize(), 'rows': [[p, time_html(p, r, i), s, r, t]
                                                      for p, s, r, t in base_rows(days.get(i) or {}, False)
                                                      if s]})
        payload['week'].setdefault('z', []).append(
            {'day': sc.DAYS[i].capitalize(), 'rows': [[p, time_html(p, r, i), s, r, t]
                                                      for p, s, r, t in base_rows(days.get(i) or {}, True)
                                                      if s]})

    for k in range(HORIZON):
        d = today + timedelta(days=k)
        if d.weekday() > 5:
            continue
        wn, kind = sc.week_info(d)
        den = kind == 'знаменатель'
        ch = changes.get(d.isoformat())
        group_ch = None
        if ch:
            for key, val in ch.items():
                if sc.canon(key) == sc.canon(name):
                    group_ch = val
                    break
        rows = merge_day(days.get(d.weekday()) or {}, den, group_ch)
        status = 'changed' if group_ch else ('empty' if ch else 'none')
        payload['days'][d.isoformat()] = {
            'label': '%s, %d %s' % (sc.DAYS[d.weekday()].capitalize(), d.day,
                                    ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
                                     'августа', 'сентября', 'октября', 'ноября', 'декабря'][d.month - 1]),
            'week': wn, 'kind': kind, 'status': status,
            'rows': [[p, time_html(p, r, d.weekday()), s, r, t] for p, s, r, t in rows],
        }
    return payload


# ---------------- html ----------------
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0f1720;color:#e6edf3;font:15px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;-webkit-tap-highlight-color:transparent}
.wrap{max-width:900px;margin:0 auto;padding:14px 14px 40px}
a{color:#5eb5f7;text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:20px;margin:6px 0 2px}
.sub{color:#8b9bab;font-size:13px;margin-bottom:12px}
.mine{display:block;background:#1d4a6e;border:1px solid #3d7fb0;border-radius:12px;padding:12px 14px;margin:0 0 16px}
.mine b{font-size:17px;display:block;color:#eaf5ff;margin-bottom:2px}
.mine span{color:#a9c4dc;font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 18px}
.chip{background:#1b2733;border:1px solid #2a3a4a;border-radius:8px;padding:7px 11px;font-size:14px;color:#e6edf3;display:inline-block}
.chip:hover{border-color:#4a7fa8;text-decoration:none}
.chip.on{background:#1d4a6e;border-color:#3d7fb0;color:#eaf5ff;font-weight:600}
h2.course{font-size:13px;color:#8b9bab;font-weight:600;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.04em}
.tabs{display:flex;gap:6px;margin:12px 0 10px}
.tabs button{flex:1;padding:10px 8px;border-radius:10px;border:1px solid #2a3a4a;background:#1b2733;color:#cfe1f2;font-size:14px;font-family:inherit;cursor:pointer}
.tabs button.on{background:#1d4a6e;border-color:#3d7fb0;color:#eaf5ff;font-weight:600}
.banner{border-radius:10px;padding:10px 12px;font-size:14px;margin:10px 0 4px;border:1px solid #2a3a4a;background:#1b2733;color:#cfe1f2}
.banner.changed{border-color:#8a6d1f;background:#2a2413;color:#ffe9a8}
.banner.none{color:#8b9bab}
.day{margin:16px 0 6px;font-size:15px;font-weight:600;color:#cfe1f2}
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
.switch{display:flex;gap:8px;margin:8px 0 4px}
.switch button{flex:1;padding:9px 10px;border-radius:9px;background:#1b2733;border:1px solid #2a3a4a;color:#cfe1f2;font-size:14px;font-family:inherit;cursor:pointer}
.switch button.on{background:#1d4a6e;border-color:#3d7fb0;color:#eaf5ff;font-weight:600}
.empty{background:#1b2733;border:1px solid #2a3a4a;border-radius:10px;padding:14px;color:#8b9bab}
input.q{width:100%;padding:11px 12px;border-radius:10px;border:1px solid #2a3a4a;background:#141e28;color:#e6edf3;font-size:15px;margin:6px 0 14px}
.foot{margin-top:26px;color:#5f7285;font-size:12px;text-align:center;line-height:1.6}
.foot a{color:#7d93a8}
"""

APP_JS = """
const G='%s', NAME='%s', COURSE='%s';
const MONTHS=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
let data=null, tab='today', parity='n';
const $=s=>document.querySelector(s);
function iso(d){const p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function table(rows){
  let h='<div class="tw"><table><thead><tr><th>№</th><th>Время</th><th>Пара</th><th>Ауд.</th><th>Преподаватель</th></tr></thead><tbody>';
  const has1=rows.some(r=>r[0]===1);
  if(!has1&&rows.length) h+='<tr><td class="n">1</td><td class="t muted">—</td><td class="s muted">—</td><td class="r muted">—</td><td class="p muted">—</td></tr>';
  for(const r of rows){
    const sub=esc(r[2])||'—', room=esc(r[3])||'—', teach=esc(r[4])||'—';
    h+='<tr><td class="n">'+r[0]+'</td><td class="t">'+(r[1]||'—')+'</td><td class="s">'+sub+'</td><td class="r">'+room+'</td><td class="p">'+teach+'</td></tr>';
  }
  return h+'</tbody></table></div>';
}
function banner(status){
  if(status==='changed') return '<div class="banner changed">🔔 Учтены изменения на эту дату.</div>';
  if(status==='empty') return '<div class="banner">Без изменений.</div>';
  return '<div class="banner none">Изменений на эту дату в сообществе пока нет.</div>';
}
function renderDay(){
  const t=new Date(); if(tab==='tomorrow') t.setDate(t.getDate()+1);
  if(t.getDay()===0) return '<div class="day">Воскресенье, '+t.getDate()+' '+MONTHS[t.getMonth()]+'</div><div class="empty">Выходной день.</div>';
  const key=iso(t), e=data.days[key];
  let h='<div class="day">'+(e?esc(e.label):'Нет данных')+'</div>';
  if(!e) return h+'<div class="empty">Расписание на эту дату ещё не собрано. Откройте «Неделя».</div>';
  h+='<div class="sub" style="margin:2px 0 0">'+esc(NAME)+' · неделя '+e.week+' · '+esc(e.kind)+'</div>';
  h+=banner(e.status);
  h+=e.rows.length?table(e.rows):'<div class="empty">Пар нет.</div>';
  return h;
}
function renderWeek(){
  let h='<div class="switch"><button id="pn" class="'+(parity==='n'?'on':'')+'">Числитель</button><button id="pz" class="'+(parity==='z'?'on':'')+'">Знаменатель</button></div>';
  const days=data.week[parity]||[];
  const now=new Date(), mon=new Date(now);
  mon.setDate(now.getDate()-((now.getDay()+6)%%7));
  days.forEach(function(d,i){
    if(!d.rows.length) return;
    const dt=new Date(mon); dt.setDate(mon.getDate()+i);
    h+='<div class="day">'+esc(d.day)+', '+dt.getDate()+' '+MONTHS[dt.getMonth()]+'</div>'+table(d.rows);
  });
  return h;
}
function paint(){
  $('#tabs').innerHTML='<button id="b1" class="'+(tab==='today'?'on':'')+'">Сегодня</button>'+
    '<button id="b2" class="'+(tab==='tomorrow'?'on':'')+'">Завтра</button>'+
    '<button id="b3" class="'+(tab==='week'?'on':'')+'">Неделя</button>';
  $('#body').innerHTML=(tab==='week')?renderWeek():renderDay();
  $('#b1').onclick=()=>{tab='today';paint();};
  $('#b2').onclick=()=>{tab='tomorrow';paint();};
  $('#b3').onclick=()=>{tab='week';paint();};
  if(tab==='week'){$('#pn').onclick=()=>{parity='n';paint();};$('#pz').onclick=()=>{parity='z';paint();};}
}
try{localStorage.setItem('ggpk.group',G);}catch(e){}
fetch('../data/g/'+G+'.json').then(r=>r.json()).then(d=>{data=d;paint();})
 .catch(()=>{$('#body').innerHTML='<div class="empty">Не удалось загрузить расписание.</div>';});
"""


def page(title, body, depth=0):
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>'
            '<meta name="description" content="Расписание занятий Губкинского горно-политехнического колледжа">'
            '<style>%s</style></head><body><div class="wrap">%s'
            '</div></body></html>' % (html.escape(title), CSS, body))


def foot():
    return ('<div class="foot">Расписание ГГПК · данные из сообщества ВК<br>'
            'обновлено %s · <a href="../prep.html">преподаватели</a>'
            % datetime.now(MSK).strftime('%d.%m %H:%M') + '</div>')


def index_page(cat, mine_map):
    parts = ['<h1>Расписание ГГПК</h1>', '<div id="mine"></div>']
    for course in sorted(cat):
        parts.append('<h2 class="course">%s</h2><div class="chips">' % html.escape(course))
        for g in sorted(cat[course]):
            parts.append('<a class="chip" href="g/%s.html" data-g="%s">%s</a>'
                         % (slug(g), slug(g), html.escape(g)))
        parts.append('</div>')
    parts.append('<h2 class="course">Ещё</h2><div class="chips">'
                 '<a class="chip" href="prep.html">🔍 Преподаватели</a></div>')
    parts.append('<div class="foot">Расписание ГГПК · данные из сообщества ВК<br>'
                 'обновлено %s</div>' % datetime.now(MSK).strftime('%d.%m %H:%M'))
    js = ('<script>var NAMES=%s;try{var g=localStorage.getItem("ggpk.group");'
          'if(g&&NAMES[g]){document.getElementById("mine").innerHTML='
          '"<a class=\\"mine\\" href=\\"g/"+g+".html\\"><b>"+NAMES[g]+"</b>'
          '<span>ваша группа · открыть расписание</span></a>";}}catch(e){}</script>'
          % json.dumps(mine_map, ensure_ascii=False))
    return page('Расписание ГГПК', ''.join(parts) + js)


def group_page(name, course, sl):
    body = ('<div class="sub"><a href="../index.html">← все группы</a></div>'
            '<h1>%s</h1><div id="tabs" class="tabs"></div><div id="body">'
            '<div class="empty">Загрузка…</div></div>' % html.escape(name))
    js = '<script>%s</script>' % (APP_JS % (sl, name, course))
    return page('%s — расписание' % name, body + js)


def teachers_index(entries):
    items = sorted(entries)
    rows = ['<a class="chip" data-n="%s" href="p/%s.html">%s</a>'
            % (html.escape(t.lower()), slug(t), html.escape(t)) for t in items]
    body = ('<h1>Преподаватели</h1><div class="sub">Всего: %d</div>'
            '<input class="q" id="q" placeholder="Фамилия, например Коваль" autocomplete="off">'
            '<div class="chips" id="list">%s</div>'
            '<p><a href="index.html">← все группы</a></p>'
            '<script>var q=document.getElementById("q"),l=document.getElementById("list");'
            'q.addEventListener("input",function(){var v=q.value.toLowerCase().trim();'
            'Array.prototype.forEach.call(l.children,function(a){'
            'a.style.display=a.dataset.n.indexOf(v)>-1?"":"none";});});</script>'
            % (len(items), ''.join(rows)))
    return page('Преподаватели', body)


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
            parts.append('<tr><td class="n">%d</td><td class="t">%s</td><td class="r">%s</td>'
                         '<td class="s">%s</td><td class="r">%s</td></tr>'
                         % (pair, time_html(pair, room, d), html.escape(g),
                            html.escape(subject or '—'), html.escape(room or '—')))
        parts.append('</tbody></table></div>')
    parts.append('<p><a href="../prep.html">← поиск</a></p>')
    return page(name, ''.join(parts))


# ---------------- сборка ----------------
NAME_RE = re.compile(r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.')


def clean_names(field):
    out = []
    for m in NAME_RE.finditer(field or ''):
        name = re.sub(r'\s+', ' ', m.group(0)).strip()
        if name.lower().startswith('вакансия'):
            continue
        if name not in out:
            out.append(name)
    return out


def collect_teachers(cat):
    names = {}
    for course in cat:
        for g in cat[course]:
            for d, cells in cat[course][g].items():
                for pair, c in cells.items():
                    for name in clean_names(c.get('teacher') or ''):
                        names.setdefault(name, []).append(
                            (g, d, pair, c.get('subject') or '', c.get('room') or ''))
    return names


def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def write_json(path, payload):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))


def local_pdf():
    path = os.path.join(HERE, 'main.pdf')
    return path if os.path.exists(path) else None


def main():
    path = local_pdf()
    if not path:
        raise SystemExit('нет main.pdf в репозитории')
    cat = sc.parse_main(path)
    total = sum(len(v) for v in cat.values())
    print('групп: %d' % total)

    changes = load_changes(os.path.join(HERE, 'changes'))
    print('дат с изменениями: %d' % len(changes))

    today = datetime.now(MSK).date()
    mine = {}
    for course in cat:
        for g in cat[course]:
            sl = slug(g)
            mine[sl] = g
            write_json('data/g/%s.json' % sl,
                       group_payload(g, course, cat[course][g], changes, today))
            write('g/%s.html' % sl, group_page(g, course, sl))

    write('index.html', index_page(cat, mine))

    t = collect_teachers(cat)
    print('преподавателей: %d' % len(t))
    write('prep.html', teachers_index(t))
    for name, entries in t.items():
        write('p/%s.html' % slug(name), prep_page(name, entries))

    write('robots.txt', 'User-agent: *\nAllow: /\n')
    print('готово: %d групп, %d страниц' % (total, total * 2))


if __name__ == '__main__':
    main()
