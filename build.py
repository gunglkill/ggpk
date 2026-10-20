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
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import schedule_core as sc  # noqa: E402

OUT = os.path.join(HERE, 'site')
MSK = timezone(timedelta(hours=5))
HORIZON = 8
VER = datetime.now(MSK).strftime('%Y%m%d%H%M')

DONATE = 'https://dalink.to/mori_iuvenis'
CHANNEL = 'https://t.me/+p3brK1bafQplNmNi'
CHAT = 'https://t.me/+WaRfhKYRo0c5YzZi'

MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
          'августа', 'сентября', 'октября', 'ноября', 'декабря']

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
    return '<br>'.join('%s–%s' % s for s in slots) if slots else '—'


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


NAME_RE = re.compile(r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.')


def clean_names(field):
    out = []
    for m in NAME_RE.finditer(field or ''):
        name = re.sub(r'\s+', ' ', m.group(0)).strip()
        if name not in out:
            out.append(name)
    return out


def group_changes(ch, name):
    if not ch:
        return None
    for key, val in ch.items():
        if sc.canon(key) == sc.canon(name):
            return val
    return None


def dates_window(today):
    out = []
    for k in range(HORIZON):
        d = today + timedelta(days=k)
        if d.weekday() > 5:
            continue
        out.append(d)
    return out


# ---------------- html ----------------
CSS = """
:root{--bg:#000;--card:#0d0d0d;--card2:#151515;--line:#1f1f1f;--line2:#2a2a2a;
--text:#fff;--muted:#8b8b8b;--pill:#fff;--pill-text:#000;--accent:#7aa2ff;
--warn-bg:#241d08;--warn-line:#7a5f1c;--warn-text:#f0d68a;--head:rgba(0,0,0,.78);
--shadow:0 16px 40px -24px rgba(0,0,0,.9)}
html[data-theme=light]{--bg:#fff;--card:#f7f7f7;--card2:#efefef;--line:#e6e6e6;--line2:#d9d9d9;
--text:#0a0a0a;--muted:#6a6a6a;--pill:#0a0a0a;--pill-text:#fff;--accent:#2563eb;
--warn-bg:#fff7dd;--warn-line:#e0c164;--warn-text:#6b5200;--head:rgba(255,255,255,.8);
--shadow:0 16px 40px -26px rgba(0,0,0,.35)}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;-webkit-tap-highlight-color:transparent}
.wrap{max-width:680px;margin:0 auto;padding:0 18px 96px}
a{color:inherit;text-decoration:none}
a:hover{text-decoration:none}
.hdr{position:sticky;top:0;z-index:20;background:var(--head);backdrop-filter:blur(16px)}
.hin{max-width:680px;margin:0 auto;display:flex;align-items:center;gap:10px;padding:14px 18px}
.brand{display:flex;align-items:center;gap:11px;min-width:0}
.brand .mark{width:38px;height:38px;flex:none;display:flex;align-items:center;justify-content:center;color:var(--text)}
.brand b{display:block;font-size:15px;font-weight:700;line-height:1.2;letter-spacing:-.01em}
.brand i{display:block;font-style:normal;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px}
.tools{margin-left:auto;display:flex;align-items:center;gap:4px}
@media (max-width:600px){.brand i{display:none}}
.ic{display:inline-flex;align-items:center;justify-content:center;gap:6px;width:36px;height:36px;border-radius:11px;border:1px solid transparent;background:transparent;color:var(--text);font-size:13px;cursor:pointer;font-family:inherit;transition:background .15s,border-color .15s;flex:none}
.ic:hover{background:var(--card2);border-color:var(--line)}
.ic:active{transform:scale(.96)}
.ic svg{display:block}
.ic.num{width:auto;min-width:36px;padding:0 9px;font-variant-numeric:tabular-nums;color:var(--muted);font-size:12.5px}
#th .i-moon{display:none}
html[data-theme=light] #th .i-sun{display:none}
html[data-theme=light] #th .i-moon{display:inline-flex}
h1{font-size:clamp(30px,7vw,44px);line-height:1.04;letter-spacing:-.035em;font-weight:800;margin:26px 0 18px}
.sub{color:var(--muted);font-size:13px;margin:-8px 0 14px}
.mine{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--card);border:1px solid var(--line2);border-radius:14px;padding:14px 16px;margin:0 0 14px;font-weight:600}
.mine span{color:var(--muted);font-size:13px;font-weight:400}
.search{display:flex;align-items:center;gap:11px;background:var(--card);border:1px solid var(--line);border-radius:15px;padding:14px 16px;margin:0 0 14px;color:var(--muted)}
.search input{flex:1;background:none;border:0;outline:none;color:var(--text);font-size:15px;font-family:inherit}
.search input::placeholder{color:var(--muted)}
.ccs{display:flex;gap:8px;overflow-x:auto;padding:2px 0 6px;margin-bottom:14px;scrollbar-width:none}
.ccs::-webkit-scrollbar{display:none}
.cc{display:inline-flex;white-space:nowrap;padding:9px 16px;border-radius:999px;background:var(--card);border:1px solid var(--line);font-size:14px;color:var(--text);cursor:pointer;transition:background .15s,color .15s,border-color .15s}
.cc.on{background:var(--pill);color:var(--pill-text);border-color:var(--pill);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media (max-width:720px){.grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width:360px){.grid{grid-template-columns:1fr}}
.gcard{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:17px 15px;border-radius:16px;background:var(--card);border:1px solid var(--line);font-size:15px;font-weight:600;letter-spacing:-.01em;transition:border-color .15s,background .15s,transform .15s}
.gcard:hover{border-color:#3a3a3a;background:#121212;transform:translateY(-1px)}
html[data-theme=light] .gcard:hover{background:#f0f0f0;border-color:#c9c9c9}
.gcard svg{color:var(--muted);flex:none}
.gcard.on{border-color:var(--pill);box-shadow:0 0 0 1px var(--pill) inset}
h2.course{font-size:12.5px;color:var(--muted);font-weight:600;margin:26px 0 8px;text-transform:uppercase;letter-spacing:.07em}
.rows{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;margin-bottom:8px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:17px 16px;border-bottom:1px solid var(--line);font-weight:600;color:var(--text);cursor:pointer}
.row:last-child{border-bottom:0}
.row:hover{background:var(--card2)}
.row span{color:var(--muted);font-size:13px;font-weight:400}
.tabs{display:flex;gap:4px;margin:14px 0 12px;padding:4px;background:var(--card2);border:1px solid var(--line);border-radius:14px}
.tabs button{flex:1;padding:11px 8px;border:0;border-radius:11px;background:transparent;color:var(--muted);font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;transition:background .18s,color .18s}
.tabs button.on{background:var(--pill);color:var(--pill-text)}
.banner{border-radius:13px;padding:12px 14px;font-size:14px;margin:12px 0 6px;border:1px solid var(--line);background:var(--card);display:flex;align-items:center;gap:9px;color:var(--muted)}
.banner.changed{border-color:var(--warn-line);background:var(--warn-bg);color:var(--warn-text)}
.banner svg{flex:none}
.day{margin:20px 0 8px;font-size:16px;font-weight:700;letter-spacing:-.01em}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:16px;background:var(--card)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:500px}
th{background:var(--card2);color:var(--muted);font-weight:600;text-align:left;padding:10px 12px;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--line)}
td{padding:12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
td.n{color:var(--muted);width:32px;text-align:center;font-variant-numeric:tabular-nums}
td.t{white-space:nowrap;width:94px;font-variant-numeric:tabular-nums}
td.s{min-width:170px}
td.r{white-space:nowrap;color:var(--muted);width:68px}
td.p{color:var(--muted);width:128px;font-size:13px}
.muted{color:var(--muted)}
.switch{display:flex;gap:4px;margin:10px 0 4px;padding:4px;background:var(--card2);border:1px solid var(--line);border-radius:14px}
.switch button{flex:1;padding:10px;border:0;border-radius:11px;background:transparent;color:var(--muted);font-size:14px;font-weight:600;font-family:inherit;cursor:pointer}
.switch button.on{background:var(--pill);color:var(--pill-text)}
.empty{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;color:var(--muted)}
input.q{width:100%;padding:13px 15px;border-radius:14px;border:1px solid var(--line);background:var(--card);color:var(--text);font-size:15px;margin:0 0 14px;font-family:inherit;outline:none}
.foot{margin:26px 0 8px;color:var(--muted);font-size:12px;text-align:center}
.bottom{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);display:flex;gap:4px;padding:4px;background:var(--card2);border:1px solid var(--line);border-radius:999px;box-shadow:var(--shadow);z-index:30}
.bottom a{display:flex;align-items:center;gap:8px;padding:11px 18px;border-radius:999px;color:var(--muted);font-size:14px;font-weight:600;white-space:nowrap}
.bottom a.on{background:var(--pill);color:var(--pill-text)}
.modal{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.7);opacity:0;pointer-events:none;transition:opacity .22s ease}
.modal.on{opacity:1;pointer-events:auto}
.mcard{width:100%;max-width:370px;background:var(--card);border:1px solid var(--line2);border-radius:22px;padding:26px 20px 18px;text-align:center;transform:translateY(18px) scale(.94);opacity:0;transition:transform .3s cubic-bezier(.16,.9,.3,1.25),opacity .22s ease}
.modal.on .mcard{transform:none;opacity:1}
.micon{display:inline-flex;align-items:center;justify-content:center;width:58px;height:58px;border-radius:18px;background:var(--card2);border:1px solid var(--line);margin-bottom:14px}
.micon svg{width:30px;height:30px}
.mtitle{font-size:18px;font-weight:700;margin-bottom:8px;line-height:1.3;letter-spacing:-.01em}
.mtext{font-size:13px;color:var(--muted);margin-bottom:20px;line-height:1.5}
.mbtn{display:block;padding:14px;border-radius:14px;background:var(--pill);color:var(--pill-text);font-weight:650;margin-bottom:8px}
.mno{width:100%;padding:12px;border-radius:14px;border:1px solid var(--line2);background:transparent;color:var(--muted);font-family:inherit;font-size:14px;cursor:pointer}
.toast{position:fixed;left:50%;bottom:82px;transform:translate(-50%,20px);opacity:0;pointer-events:none;max-width:calc(100% - 28px);background:var(--card2);border:1px solid var(--line2);color:var(--text);padding:11px 16px;border-radius:12px;font-size:13.5px;line-height:1.4;text-align:center;z-index:120;box-shadow:0 10px 30px rgba(0,0,0,.5);transition:opacity .2s ease,transform .26s cubic-bezier(.16,.9,.3,1.25)}
.toast.on{opacity:1;transform:translate(-50%,0)}
"""

THEME_JS = ("try{var t=localStorage.getItem('ggpk.theme');"
            "if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}")


def ic(path, size=18):
    return ('<svg viewBox="0 0 24 24" width="%d" height="%d" fill="none" stroke="currentColor" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
            % (size, size, path))


I_SUN = ic('<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4'
           'M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>')
I_MOON = ic('<path d="M20.5 14.6A8.6 8.6 0 0 1 9.4 3.5a8.6 8.6 0 1 0 11.1 11.1z"/>')
I_CLOCK = ic('<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 1.8"/>', 16)
I_USERS = ic('<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5.6 6-5.6s6 2.3 6 5.6"/>'
             '<path d="M16.2 5.3a3 3 0 0 1 0 5.4M17.8 14.7c2.1.6 3.4 2.3 3.4 4.4"/>', 16)
I_HEART = ic('<path d="M12 20.4S4.6 15.9 4.6 11A4.1 4.1 0 0 1 12 8.4 4.1 4.1 0 0 1 19.4 11'
             'c0 4.9-7.4 9.4-7.4 9.4z"/>')
I_HORN = ic('<path d="M3.5 11v2a1 1 0 0 0 1 1h2.2l4.3 4V6l-4.3 4H4.5a1 1 0 0 0-1 1z"/>'
            '<path d="M14.5 8.5a4 4 0 0 1 0 7M17.5 6a8 8 0 0 1 0 12"/>')
I_CHAT = ic('<path d="M4 5.5h16v10.2H8.6L4 19.6z"/>')
I_SEARCH = ic('<circle cx="11" cy="11" r="6.2"/><path d="M15.6 15.6L20 20"/>')
I_BELL = ic('<path d="M6.5 17h11l-1.3-2.2V10a4.2 4.2 0 1 0-8.4 0v4.8z"/>'
            '<path d="M10.3 19.5a1.9 1.9 0 0 0 3.4 0"/>', 16)

I_LOGO = ('<svg viewBox="0 0 40 40" width="38" height="38">'
         '<rect x="1" y="1" width="38" height="38" rx="11" fill="currentColor" fill-opacity=".07" '
         'stroke="currentColor" stroke-opacity=".22"/>'
         '<path d="M9 11.5h22" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
         '<circle cx="20" cy="23" r="8.4" fill="none" stroke="currentColor" stroke-width="1.9"/>'
         '<ellipse cx="20" cy="23" rx="3.9" ry="8.4" fill="none" stroke="currentColor" stroke-width="1.9"/>'
         '<path d="M11.9 20.4h16.2M11.9 25.6h16.2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
         '</svg>')
I_CHEV = ic('<path d="M9 5.5l6.5 6.5L9 18.5"/>', 16)
I_GRID = ic('<rect x="3" y="3" width="7.5" height="7.5" rx="2.2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2.2"/>'
            '<rect x="3" y="13.5" width="7.5" height="7.5" rx="2.2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2.2"/>', 17)
I_TEACH = ic('<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20.5c0-3.6 3.2-6.1 7.5-6.1s7.5 2.5 7.5 6.1"/>', 17)
I_RUB = ('<svg viewBox="0 0 220 220" width="18" height="18" fill="#2ecc71">'
         '<path d="M110,0C49.346,0,0,49.346,0,110s49.346,110,110,110s110-49.346,110-110S170.654,0,110,0z '
         'M110,210c-55.141,0-100-44.86-100-100S54.859,10,110,10s100,44.86,100,100S165.141,210,110,210z"/>'
         '<path d="M110,19.5c-49.902,0-90.5,40.598-90.5,90.5s40.598,90.5,90.5,90.5s90.5-40.598,90.5-90.5'
         'S159.902,19.5,110,19.5z M110,197.5c-48.248,0-87.5-39.252-87.5-87.5S61.752,22.5,110,22.5'
         's87.5,39.252,87.5,87.5S158.248,197.5,110,197.5z"/>'
         '<polygon points="103.382,133.87 93.382,133.87 93.382,144.887 84.632,144.887 84.632,154.887 '
         '112.132,154.887 112.132,144.887 103.382,144.887"/>'
         '<path d="M123.062,57.773H83.077v12h10.305v33.876H83.077v12h10.305v2.22h10v-2.22h19.68'
         'c15.957,0,28.938-12.981,28.938-28.938S139.019,57.773,123.062,57.773z M123.062,103.65h-19.68V69.773h19.68'
         'c9.34,0,16.938,7.599,16.938,16.938S132.401,103.65,123.062,103.65z"/>'
         '<rect x="83.077" y="119.87" width="53.989" height="12"/></svg>')
I_TG = ('<svg viewBox="0 0 100 100" width="18" height="18" fill="#229ED9">'
        '<path d="M88.723,12.142C76.419,17.238,23.661,39.091,9.084,45.047c-9.776,3.815-4.053,7.392-4.053,7.392'
        's8.345,2.861,15.499,5.007c7.153,2.146,10.968-0.238,10.968-0.238l33.62-22.652c11.922-8.107,9.061-1.431,6.199,1.431'
        'c-6.199,6.2-16.452,15.975-25.036,23.844c-3.815,3.338-1.908,6.199-0.238,7.63c6.199,5.246,23.129,15.976,24.082,16.691'
        'c5.037,3.566,14.945,8.699,16.452-2.146c0,0,5.961-37.435,5.961-37.435c1.908-12.637,3.815-24.321,4.053-27.659'
        'C97.307,8.804,88.723,12.142,88.723,12.142z"/></svg>')

MODAL_HTML = ('<div class="modal" id="m"><div class="mcard">'
              '<div class="micon" id="micon"></div>'
              '<div class="mtitle" id="mtitle"></div>'
              '<div class="mtext" id="mtext"></div>'
              '<a class="mbtn" id="mgo" href="#" target="_blank" rel="noopener"></a>'
              '<button class="mno" id="mno">Закрыть</button>'
              '</div></div>'
              '<span id="ic-donate" hidden>%s</span>'
              '<span id="ic-tg" hidden>%s</span>' % (I_RUB, I_TG))

HEADER_EXTRA = """
<script>
(function(){
  var root=document.documentElement;
  var MODAL={
    donate:{t:'Хотите поддержать проект?',
            x:'Это поможет оплатить сервер, чтобы расписание работало круглосуточно и без пропусков.',
            b:'Донат', u:'__DONATE__', i:'ic-donate'},
    tg:{t:'Хотите перейти в Telegram-канал разработчика?',
        x:'Там логи обновлений, новости проекта и всё, что меняется на сайте.',
        b:'Перейти', u:'__CHANNEL__', i:'ic-tg'}
  };
  function openModal(k){
    var d=MODAL[k]; if(!d) return;
    var src=document.getElementById(d.i);
    var box=document.getElementById('micon');
    if(box) box.innerHTML=src?src.innerHTML:'';
    var t=document.getElementById('mtitle'); if(t) t.textContent=d.t;
    var x=document.getElementById('mtext'); if(x) x.textContent=d.x;
    var go=document.getElementById('mgo');
    if(go){go.textContent=d.b; go.href=d.u;}
    var m=document.getElementById('m'); if(m) m.classList.add('on');
  }
  function closeModal(){
    var m=document.getElementById('m'); if(m) m.classList.remove('on');
  }
  function toggle(){
    var next=(root.getAttribute('data-theme')==='light')?'dark':'light';
    root.setAttribute('data-theme',next);
    try{localStorage.setItem('ggpk.theme',next);}catch(e){}
  }
  function pad(n){return (n<10?'0':'')+n}
  var tmLeft='--:--';
  function tick(){
    var now=new Date(), next=new Date(now);
    next.setMinutes(7,0,0);
    if(next<=now) next.setHours(next.getHours()+1,7,0,0);
    var s=Math.round((next-now)/1000), m=Math.floor(s/60), r=s%60;
    tmLeft=m+':'+(r<10?'0':'')+r;
    var el=document.getElementById('tmt');
    if(el) el.textContent=tmLeft;
  }
  var toastT=null;
  function toast(txt){
    var el=document.getElementById('toast'); if(!el) return;
    el.textContent=txt; el.classList.add('on');
    if(toastT) clearTimeout(toastT);
    toastT=setTimeout(function(){el.classList.remove('on');},5000);
  }
  document.addEventListener('click',function(e){
    var th=e.target.closest?e.target.closest('#th'):null;
    if(th){toggle();return;}
    var st=e.target.closest?e.target.closest('#st'):null;
    if(st){var n=document.getElementById('stt');
      toast('Пользователей за сегодня: '+(n?n.textContent:'—'));return;}
    var tm=e.target.closest?e.target.closest('#tm'):null;
    if(tm){toast('До обновления расписания: '+tmLeft);return;}
    var b=e.target.closest?e.target.closest('[data-modal]'):null;
    if(b){e.preventDefault();openModal(b.getAttribute('data-modal'));return;}
    if(e.target.id==='m'||(e.target.closest&&e.target.closest('#mno'))){closeModal();}
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
  tick(); setInterval(tick,20000);
  try{
    var el=document.getElementById('stt');
    var cached=sessionStorage.getItem('ggpk.stat');
    if(cached&&el){el.textContent=cached;}
    else if(el){
      fetch('https://hitscounter.dev/api/hit?url=ggpk-schedule&color=%235eb5f7')
        .then(function(r){return r.text();})
        .then(function(t){
          var a=t.indexOf('aria-label="');
          if(a<0) return;
          var v=t.slice(a+12); v=v.slice(0, v.indexOf('"'));
          var p=v.split('/');
          var today=(p[0]||'').trim(), total=(p[1]||'').trim();
          if(!today) return;
          el.textContent=today;
          el.parentNode.title='Сегодня: '+today+' · всего: '+total;
          sessionStorage.setItem('ggpk.stat', today);
        }).catch(function(){});
    }
  }catch(e){}
})();
</script>
"""


TOAST_HTML = '<div class="toast" id="toast"></div>'


def head(title):
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>'
            '<meta name="description" content="Расписание занятий Губкинского горно-политехнического колледжа">'
            '<style>%s</style><script>%s</script></head><body>'
            % (html.escape(title), CSS, THEME_JS))


def header(home='index.html'):
    return ('<header class="hdr"><div class="hin">'
            '<a class="brand" href="%s"><span class="mark">%s</span>'
            '<span class="bt"><b>Расписание</b>'
            '<i>Губкинский горно-политехнический колледж</i></span></a>'
            '<div class="tools">'
            '<button class="ic" id="tm" title="До обновления расписания">%s</button>'
            '<span class="ic num" id="st" title="Просмотров за сегодня">%s'
            '<span id="stt">—</span></span>'
            '<a class="ic" href="%s" data-modal="tg" target="_blank" rel="noopener" '
            'title="Канал с обновлениями">%s</a>'
            '<a class="ic" href="%s" data-modal="donate" target="_blank" rel="noopener" '
            'title="Поддержать проект">%s</a>'
            '<button class="ic" id="th" title="Сменить тему">'
            '<span class="i-sun">%s</span><span class="i-moon">%s</span></button>'
            '</div></div></header>'
            % (home, I_LOGO, I_CLOCK, I_USERS, CHANNEL, I_TG, DONATE, I_RUB, I_SUN, I_MOON))


def foot():
    return ('<div class="foot">данные сообщества ВК · обновлено %s</div>'
            % datetime.now(MSK).strftime('%d.%m %H:%M'))


def bottom_nav(active, up=''):
    items = [('groups', up + 'index.html', I_GRID, 'Группы'),
             ('teachers', up + 'prep.html', I_TEACH, 'Преподаватели')]
    out = ['<nav class="bottom">']
    for key, href, icon, label in items:
        out.append('<a class="%s" href="%s">%s<span>%s</span></a>'
                   % ('on' if key == active else '', href, icon, label))
    out.append('</nav>')
    return ''.join(out)


def page(title, body, home='index.html', up='', nav='groups'):
    noscript = ('<noscript><div class="wrap"><div class="empty">Включите JavaScript — '
                'без него расписание не отобразится.</div></div></noscript>')
    tail = HEADER_EXTRA.replace('__DONATE__', DONATE).replace('__CHANNEL__', CHANNEL)
    return (head(title) + header(home) + noscript +
            '<div class="wrap">' + body + foot() + '</div>' +
            bottom_nav(nav, up) + MODAL_HTML + TOAST_HTML + tail + '</body></html>')


def index_page(cat, mine):
    courses = [(course, sorted(cat[course])) for course in sorted(cat)]
    parts = ['<h1>Расписание занятий</h1>', '<div id="mine"></div>',
             '<div class="search">', I_SEARCH,
             '<input id="q" placeholder="Найти группу" autocomplete="off"></div>',
             '<div class="ccs" id="ccs">']
    for i, (course, groups) in enumerate(courses):
        parts.append('<span class="cc%s" data-c="%d">%s</span>'
                     % (' on' if i == 0 else '', i, html.escape(course)))
    parts.append('</div><div class="grid" id="grid">')
    for i, (course, groups) in enumerate(courses):
        for g in groups:
            parts.append('<a class="gcard" href="g/%s.html?v=%s" data-c="%d" data-n="%s">'
                         '<span>%s</span>%s</a>'
                         % (slug(g), VER, i, html.escape(g.lower()), html.escape(g), I_CHEV))
    parts.append('</div>')
    parts.append('<h2 class="course">Ещё</h2><div class="rows">'
                 '<a class="row" href="%s" data-modal="tg" target="_blank" rel="noopener">'
                 'Канал с обновлениями<span>Telegram</span></a>'
                 '<a class="row" href="%s" data-modal="donate" target="_blank" rel="noopener">'
                 'Поддержать проект<span>DonationAlerts</span></a></div>'
                 % (CHANNEL, DONATE))
    js = ('<script>var NAMES=%s,q=document.getElementById("q"),grid=document.getElementById("grid"),'
          'ccs=document.getElementById("ccs"),cur=0;'
          'try{var g=localStorage.getItem("ggpk.group");if(g&&NAMES[g]){'
          'document.getElementById("mine").innerHTML='
          '"<a class=\\"mine\\" href=\\"g/"+g+".html\\"><b></b>'
          '<span></span></a>";'
          'var el=document.getElementById("mine").firstChild;'
          'el.firstChild.textContent=NAMES[g];el.lastChild.textContent="ваша группа";}}catch(e){}'
          'function apply(){var v=(q.value||"").toLowerCase().trim();'
          'Array.prototype.forEach.call(grid.children,function(c){'
          'var okC=v?true:c.getAttribute("data-c")===String(cur);'
          'var okT=c.getAttribute("data-n").indexOf(v)>-1;c.hidden=!(okC&&okT);});}'
          'ccs.addEventListener("click",function(e){var t=e.target.closest(".cc");if(!t)return;'
          'cur=+t.getAttribute("data-c");'
          'Array.prototype.forEach.call(ccs.children,function(a){a.classList.toggle("on",a===t);});'
          'apply();});'
          'q.addEventListener("input",apply);apply();</script>' % json.dumps(mine, ensure_ascii=False))
    return page('Расписание ГГПК', ''.join(parts) + js)


APP_JS = """
const G='%s', NAME='%s', MODE='%s';
const MONTHS=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
let data=null, tab='today', parity='n';
const $=s=>document.querySelector(s);
function iso(d){const p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function table(rows){
  const h5=(MODE==='t')?'Пара':'Преподаватель';
  let h='<div class="tw"><table><thead><tr><th>№</th><th>Время</th><th>'+(MODE==='t'?'Группа':'Пара')+'</th><th>Ауд.</th><th>'+h5+'</th></tr></thead><tbody>';
  if(!rows.some(r=>r[0]===1)&&rows.length){
    h+='<tr><td class="n">1</td><td class="t muted">—</td><td class="s muted">—</td><td class="r muted">—</td><td class="p muted">—</td></tr>';
  }
  for(const r of rows){
    const c3=esc(r[2])||'—', c4=esc(r[3])||'—', c5=esc(r[4])||'—';
    if(MODE==='t'){
      h+='<tr><td class="n">'+r[0]+'</td><td class="t">'+(r[1]||'—')+'</td><td class="r">'+c3+'</td><td class="r">'+c5+'</td><td class="s">'+c4+'</td></tr>';
    }else{
      h+='<tr><td class="n">'+r[0]+'</td><td class="t">'+(r[1]||'—')+'</td><td class="s">'+c3+'</td><td class="r">'+c4+'</td><td class="p">'+c5+'</td></tr>';
    }
  }
  return h+'</tbody></table></div>';
}
function banner(status){
  if(status==='changed') return '<div class="banner changed">%s Учтены изменения на эту дату.</div>';
  if(status==='empty') return '<div class="banner">Без изменений.</div>';
  return '<div class="banner none">Изменений на эту дату в сообществе пока нет.</div>';
}
function renderDay(){
  let t=new Date();
  if(tab==='tomorrow'){ t.setDate(t.getDate()+1); if(t.getDay()===0) t.setDate(t.getDate()+1); }
  if(t.getDay()===0) return '<div class="day">Воскресенье, '+t.getDate()+' '+MONTHS[t.getMonth()]+'</div><div class="empty">Сегодня выходной. Занятий нет.</div>';
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
  if(!days.some(d=>d.rows.length)) h+='<div class="empty">Пар нет.</div>';
  return h;
}
function paint(){
  const nextName=(new Date().getDay()===5)?'Понедельник':'Завтра';
  $('#tabs').innerHTML='<button id="b1" class="'+(tab==='today'?'on':'')+'">Сегодня</button>'+
    '<button id="b2" class="'+(tab==='tomorrow'?'on':'')+'">'+nextName+'</button>'+
    '<button id="b3" class="'+(tab==='week'?'on':'')+'">Неделя</button>';
  $('#body').innerHTML=(tab==='week')?renderWeek():renderDay();
  $('#b1').onclick=()=>{tab='today';paint();};
  $('#b2').onclick=()=>{tab='tomorrow';paint();};
  $('#b3').onclick=()=>{tab='week';paint();};
  if(tab==='week'){$('#pn').onclick=()=>{parity='n';paint();};$('#pz').onclick=()=>{parity='z';paint();};}
}
if(MODE==='g'){try{localStorage.setItem('ggpk.group',G);}catch(e){}}
var watchdog=setTimeout(function(){
  if(!data){var b=document.getElementById('body');
    if(b) b.innerHTML='<div class="empty">Долго нет ответа. Проверьте интернет и обновите страницу.</div>';}
},7000);
fetch('../data/'+(MODE==='t'?'p':'g')+'/'+G+'.json?v=%s').then(r=>r.json()).then(d=>{data=d;clearTimeout(watchdog);paint();})
 .catch(()=>{clearTimeout(watchdog);$('#body').innerHTML='<div class="empty">Не удалось загрузить расписание.</div>';});
"""


def app_page(title, slug_, name, mode):
    if mode == 't':
        back = '<a href="../prep.html?v=%s">← преподаватели</a>' % VER
        nav = 'teachers'
    else:
        back = '<a href="../index.html?v=%s">← все группы</a>' % VER
        nav = 'groups'
    body = ('<div class="sub">%s</div>'
            '<h1>%s</h1><div id="tabs" class="tabs"></div><div id="body">'
            '<div class="empty">Загрузка…</div></div>' % (back, html.escape(name)))
    js = '<script>%s</script>' % (APP_JS % (slug_, name.replace("'", "\\'"), mode, I_BELL, VER))
    return page(title, body + js, home='../index.html', up='../', nav=nav)


def prep_index(teachers):
    items = sorted(teachers)
    rows = ['<a class="gcard" data-n="%s" href="p/%s.html?v=%s" style="grid-column:span 2">'
            '<span>%s</span>%s</a>'
            % (html.escape(t.lower()), slug(t), VER, html.escape(t), I_CHEV) for t in items]
    body = ('<h1>Преподаватели</h1>'
            '<div class="search">%s<input id="q" placeholder="Найти преподавателя" '
            'autocomplete="off"></div>'
            '<div class="grid" id="grid">%s</div>'
            '<script>var q=document.getElementById("q"),g=document.getElementById("grid");'
            'q.addEventListener("input",function(){var v=q.value.toLowerCase().trim();'
            'Array.prototype.forEach.call(g.children,function(a){'
            'a.hidden=a.getAttribute("data-n").indexOf(v)<0;});});</script>'
            % (I_SEARCH, ''.join(rows)))
    return page('Преподаватели', body, nav='teachers')


# ---------------- сборка ----------------
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


def week_block(days, den, mapper):
    out = []
    for i in range(6):
        rows = []
        for pair, subject, room, teacher in base_rows(days.get(i) or {}, den):
            if not subject:
                continue
            rows.append(mapper(pair, time_html(pair, room, i), subject, room, teacher))
        out.append({'day': sc.DAYS[i].capitalize(), 'rows': rows})
    return out


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
    dates = dates_window(today)
    label = {d.isoformat(): '%s, %d %s' % (sc.DAYS[d.weekday()].capitalize(), d.day,
                                           MONTHS[d.month - 1]) for d in dates}

    merged = {}
    for d in dates:
        iso = d.isoformat()
        ch = changes.get(iso)
        merged[iso] = {}
        for course in cat:
            for g in cat[course]:
                den = sc.week_info(d)[1] == 'знаменатель'
                merged[iso][g] = merge_day(cat[course][g].get(d.weekday()) or {}, den,
                                           group_changes(ch, g))

    mine = {}
    for course in cat:
        for g in cat[course]:
            sl = slug(g)
            mine[sl] = g
            payload = {'name': g, 'course': course, 'today': today.isoformat(), 'days': {}, 'week': {}}
            payload['week']['n'] = week_block(cat[course][g], False,
                                              lambda p, t, s, r, te: [p, t, s, r, te])
            payload['week']['z'] = week_block(cat[course][g], True,
                                              lambda p, t, s, r, te: [p, t, s, r, te])
            for d in dates:
                iso = d.isoformat()
                ch = changes.get(iso)
                gc = group_changes(ch, g)
                rows = merged[iso][g]
                payload['days'][iso] = {
                    'label': label[iso],
                    'week': sc.week_info(d)[0],
                    'kind': sc.week_info(d)[1],
                    'status': 'changed' if gc else ('empty' if ch else 'none'),
                    'rows': [[p, time_html(p, r, d.weekday()), s, r, te] for p, s, r, te in rows],
                }
            write_json('data/g/%s.json' % sl, payload)
            write('g/%s.html' % sl, app_page('%s — расписание' % g, sl, g, 'g'))

    write('index.html', index_page(cat, mine))

    # преподаватели
    teachers = {}
    for course in cat:
        for g in cat[course]:
            for d, cells in cat[course][g].items():
                for pair, c in cells.items():
                    subj = c.get('subject') or ''
                    for name in clean_names(c.get('teacher') or ''):
                        teachers.setdefault(name, {'groups': set()})['groups'].add(g)
                    for name in clean_names(c.get('teacher_den') or ''):
                        teachers.setdefault(name, {'groups': set()})['groups'].add(g)

    print('преподавателей: %d' % len(teachers))
    for name in teachers:
        sl = slug(name)
        payload = {'name': name, 'course': '', 'today': today.isoformat(), 'days': {}, 'week': {}}
        payload['week']['n'] = teacher_week(cat, name, False)
        payload['week']['z'] = teacher_week(cat, name, True)
        for d in dates:
            iso = d.isoformat()
            rows = []
            base = []
            for course in cat:
                for g in cat[course]:
                    for p, s, r, te in base_rows(cat[course][g].get(d.weekday()) or {},
                                                 sc.week_info(d)[1] == 'знаменатель'):
                        if s and name in clean_names(te):
                            base.append((p, g, s, r))
            for course in cat:
                for g in cat[course]:
                    for p, s, r, te in merged[iso][g]:
                        if name in clean_names(te):
                            rows.append([p, time_html(p, r, d.weekday()), g, s, r])
            rows.sort(key=lambda x: (x[0], x[2]))
            base.sort(key=lambda x: (x[0], x[1]))
            status = 'changed' if [tuple(x) for x in base] != [(r[0], r[2], r[3], r[4]) for r in rows] else 'none'
            payload['days'][iso] = {
                'label': label[iso], 'week': sc.week_info(d)[0], 'kind': sc.week_info(d)[1],
                'status': status, 'rows': rows,
            }
        write_json('data/p/%s.json' % sl, payload)
        write('p/%s.html' % sl, app_page('%s — расписание' % name, sl, name, 't'))

    write('prep.html', prep_index(teachers))
    write('robots.txt', 'User-agent: *\nAllow: /\n')
    print('готово')


def teacher_week(cat, name, den):
    out = []
    for i in range(6):
        rows = []
        for course in cat:
            for g in cat[course]:
                for p, s, r, te in base_rows(cat[course][g].get(i) or {}, den):
                    if s and name in clean_names(te):
                        rows.append([p, time_html(p, r, i), g, s, r])
        rows.sort(key=lambda x: (x[0], x[2]))
        out.append({'day': sc.DAYS[i].capitalize(), 'rows': rows})
    return out


if __name__ == '__main__':
    main()
