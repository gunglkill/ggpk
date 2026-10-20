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
:root{--bg:#0f1720;--card:#141e28;--card2:#1b2733;--line:#263442;--line2:#2a3a4a;
--text:#e6edf3;--muted:#8b9bab;--accent:#5eb5f7;--accent-bg:#1d4a6e;--accent-line:#3d7fb0;
--warn-bg:#2a2413;--warn-line:#8a6d1f;--warn-text:#ffe9a8;--head:rgba(15,23,32,.88)}
html[data-theme=light]{--bg:#f2f5f9;--card:#ffffff;--card2:#e9eef5;--line:#d7dfe9;--line2:#c9d4e1;
--text:#16202b;--muted:#5d6f80;--accent:#1a6fb0;--accent-bg:#dbeafe;--accent-line:#8bc0e8;
--warn-bg:#fff6d6;--warn-line:#e0c05a;--warn-text:#6b5200;--head:rgba(242,245,249,.9)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;-webkit-tap-highlight-color:transparent}
.wrap{max-width:900px;margin:0 auto;padding:0 14px 40px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.hdr{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;
gap:10px;padding:10px 14px;background:var(--head);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);margin-bottom:12px}
.hleft,.hright{display:flex;align-items:center;gap:8px}
.ic{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-width:38px;height:36px;padding:0 10px;
border-radius:10px;border:1px solid var(--line2);background:var(--card2);color:var(--text);font-size:15px;cursor:pointer;font-family:inherit}
.ic:hover{border-color:var(--accent-line);text-decoration:none}
.ic.timer{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
h1{font-size:20px;margin:6px 0 2px}
.sub{color:var(--muted);font-size:13px;margin-bottom:12px}
.mine{display:block;background:var(--accent-bg);border:1px solid var(--accent-line);border-radius:12px;padding:12px 14px;margin:0 0 16px}
.mine b{font-size:17px;display:block;margin-bottom:2px}
.mine span{color:var(--muted);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 16px}
.chip{background:var(--card2);border:1px solid var(--line2);border-radius:8px;padding:7px 11px;font-size:14px;color:var(--text);display:inline-block;cursor:pointer}
.chip:hover{border-color:var(--accent-line);text-decoration:none}
.chip.on{background:var(--accent-bg);border-color:var(--accent-line);font-weight:600}
h2.course{font-size:13px;color:var(--muted);font-weight:600;margin:16px 0 6px;text-transform:uppercase;letter-spacing:.04em}
.tabs{display:flex;gap:6px;margin:12px 0 10px}
.tabs button{flex:1;padding:10px 8px;border-radius:10px;border:1px solid var(--line2);background:var(--card2);color:var(--text);font-size:14px;font-family:inherit;cursor:pointer}
.tabs button.on{background:var(--accent-bg);border-color:var(--accent-line);font-weight:600}
.banner{border-radius:10px;padding:10px 12px;font-size:14px;margin:10px 0 4px;border:1px solid var(--line2);background:var(--card2)}
.banner.changed{border-color:var(--warn-line);background:var(--warn-bg);color:var(--warn-text)}
.banner.none{color:var(--muted)}
.day{margin:16px 0 6px;font-size:15px;font-weight:600}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:520px}
th{background:var(--card2);color:var(--muted);font-weight:600;text-align:left;padding:8px 10px;font-size:12px;text-transform:uppercase;letter-spacing:.03em;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
td.n{color:var(--muted);width:34px;text-align:center}
td.t{white-space:nowrap;width:96px;font-variant-numeric:tabular-nums}
td.s{min-width:170px}
td.r{white-space:nowrap;color:var(--muted);width:70px}
td.p{color:var(--muted);width:130px;font-size:13px}
.muted{color:var(--muted)}
.switch{display:flex;gap:8px;margin:8px 0 4px}
.switch button{flex:1;padding:9px 10px;border-radius:9px;background:var(--card2);border:1px solid var(--line2);color:var(--text);font-size:14px;font-family:inherit;cursor:pointer}
.switch button.on{background:var(--accent-bg);border-color:var(--accent-line);font-weight:600}
.empty{background:var(--card2);border:1px solid var(--line2);border-radius:10px;padding:14px;color:var(--muted)}
input.q{width:100%;padding:11px 12px;border-radius:10px;border:1px solid var(--line2);background:var(--card);color:var(--text);font-size:15px;margin:6px 0 14px}
.foot{margin-top:26px;color:var(--muted);font-size:12px;text-align:center;line-height:1.7}
.foot a{color:var(--muted)}
.links{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin:18px 0 6px}
.links a{background:var(--card2);border:1px solid var(--line2);border-radius:10px;padding:9px 12px;font-size:13px;color:var(--text)}
"""

THEME_JS = ("try{var t=localStorage.getItem('ggpk.theme');"
            "if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}")

HEADER_EXTRA = """
<script>
(function(){
  var root=document.documentElement;
  function icon(){var b=document.getElementById('th'); if(b) b.textContent=(root.getAttribute('data-theme')==='light')?'🌙':'☀️';}
  function toggle(){
    var next=(root.getAttribute('data-theme')==='light')?'dark':'light';
    root.setAttribute('data-theme',next);
    try{localStorage.setItem('ggpk.theme',next);}catch(e){}
    icon();
  }
  function pad(n){return (n<10?'0':'')+n}
  function tick(){
    var now=new Date(), next=new Date(now);
    next.setMinutes(7,0,0);
    if(next<=now) next.setHours(next.getHours()+1,7,0,0);
    var s=Math.round((next-now)/1000), m=Math.floor(s/60), r=s%60;
    var el=document.getElementById('tm');
    if(el) el.textContent='⏳ '+m+':'+(r<10?'0':'')+r;
  }
  document.addEventListener('click',function(e){
    if(e.target&&e.target.id==='th'){toggle();}
  });
  icon(); tick(); setInterval(tick,20000);
  try{
    var d=new Date(); var key=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
    var seen=sessionStorage.getItem('ggpk.v');
    if(!seen) sessionStorage.setItem('ggpk.v','1');
    var url='https://abacus.jasoncameron.dev/'+(seen?'get':'hit')+'/ggpk-site/views-'+key;
    fetch(url).then(function(r){return r.ok?r.json():null;}).then(function(j){
      var el=document.getElementById('st');
      if(el&&j&&j.value!=null) el.textContent='👥 '+j.value;
    }).catch(function(){});
  }catch(e){}
})();
</script>
"""


def head(title):
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>'
            '<meta name="description" content="Расписание занятий Губкинского горно-политехнического колледжа">'
            '<style>%s</style><script>%s</script></head><body>'
            % (html.escape(title), CSS, THEME_JS))


def header():
    return ('<header class="hdr"><div class="hleft">'
            '<button class="ic" id="th" title="Сменить тему">☀️</button>'
            '<span class="ic timer" id="tm" title="До обновления расписания">⏳ --:--</span>'
            '<span class="ic timer" id="st" title="Просмотров за сегодня">👥 —</span>'
            '</div><div class="hright">'
            '<a class="ic" href="%s" target="_blank" rel="noopener" title="Поддержать проект">❤️</a>'
            '<a class="ic" href="%s" target="_blank" rel="noopener" title="Канал с обновлениями">📢</a>'
            '</div></header>' % (DONATE, CHANNEL))


def foot():
    return ('<div class="links">'
            '<a href="%s" target="_blank" rel="noopener">❤️ Поддержать проект</a>'
            '<a href="%s" target="_blank" rel="noopener">📢 Канал с обновлениями</a>'
            '<a href="%s" target="_blank" rel="noopener">💬 Чат</a>'
            '</div>'
            '<div class="foot">Расписание ГГПК · данные из сообщества ВК<br>'
            'обновлено %s · сборка каждый час</div>'
            % (DONATE, CHANNEL, CHAT, datetime.now(MSK).strftime('%d.%m %H:%M')))


def page(title, body):
    return head(title) + header() + '<div class="wrap">' + body + foot() + \
        '</div>' + HEADER_EXTRA + '</body></html>'


# ---------------- страницы ----------------
def index_page(cat, mine):
    courses = []
    for course in sorted(cat):
        courses.append((course, sorted(cat[course])))
    parts = ['<h1>Расписание ГГПК</h1>', '<div id="mine"></div>',
             '<div class="chips" id="courses">']
    for i, (course, groups) in enumerate(courses):
        parts.append('<span class="chip%s" data-c="%d">%s</span>'
                     % (' on' if i == 0 else '', i, html.escape(course)))
    parts.append('</div><div id="lists">')
    for i, (course, groups) in enumerate(courses):
        parts.append('<div class="clist" data-c="%d"%s>' % (i, '' if i == 0 else ' hidden'))
        for g in groups:
            parts.append('<a class="chip" href="g/%s.html" data-g="%s">%s</a>'
                         % (slug(g), slug(g), html.escape(g)))
        parts.append('</div>')
    parts.append('</div>')
    parts.append('<h2 class="course">Ещё</h2><div class="chips">'
                 '<a class="chip" href="prep.html">🔍 Преподаватели</a></div>')
    js = ('<script>var NAMES=%s;'
          'try{var g=localStorage.getItem("ggpk.group");if(g&&NAMES[g]){'
          'document.getElementById("mine").innerHTML='
          '"<a class=\\"mine\\" href=\\"g/"+g+".html\\"><b>"+NAMES[g]+"</b>'
          '<span>ваша группа · открыть расписание</span></a>";}}catch(e){}'
          'document.getElementById("courses").addEventListener("click",function(e){'
          'var t=e.target.closest("[data-c]");if(!t)return;'
          'var i=t.getAttribute("data-c");'
          'Array.prototype.forEach.call(document.querySelectorAll("#courses .chip"),function(a){a.classList.toggle("on",a===t);});'
          'Array.prototype.forEach.call(document.querySelectorAll(".clist"),function(a){'
          'a.hidden=a.getAttribute("data-c")!==i;});});'
          '</script>' % json.dumps(mine, ensure_ascii=False))
    return page('Расписание ГГПК', ''.join(parts) + js)


APP_JS = """
const G='%s', NAME='%s', MODE='%s';
const MONTHS=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
let data=null, tab='today', parity='n';
const $=s=>document.querySelector(s);
function iso(d){const p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function table(rows){
  const h5=(MODE==='t')?'Группа':'Преподаватель';
  let h='<div class="tw"><table><thead><tr><th>№</th><th>Время</th><th>'+(MODE==='t'?'Группа':'Пара')+'</th><th>Ауд.</th><th>'+h5+'</th></tr></thead><tbody>';
  if(!rows.some(r=>r[0]===1)&&rows.length){
    h+='<tr><td class="n">1</td><td class="t muted">—</td><td class="s muted">—</td><td class="r muted">—</td><td class="p muted">—</td></tr>';
  }
  for(const r of rows){
    const c3=esc(r[2])||'—', c4=esc(r[3])||'—', c5=esc(r[4])||'—';
    if(MODE==='t'){
      h+='<tr><td class="n">'+r[0]+'</td><td class="t">'+(r[1]||'—')+'</td><td class="s">'+c3+'</td><td class="r">'+c5+'</td><td class="p">'+c4+'</td></tr>';
    }else{
      h+='<tr><td class="n">'+r[0]+'</td><td class="t">'+(r[1]||'—')+'</td><td class="s">'+c3+'</td><td class="r">'+c4+'</td><td class="p">'+c5+'</td></tr>';
    }
  }
  return h+'</tbody></table></div>';
}
function banner(status){
  if(status==='changed') return '<div class="banner changed">🔔 Учтены изменения на эту дату.</div>';
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
fetch('../data/'+(MODE==='t'?'p':'g')+'/'+G+'.json').then(r=>r.json()).then(d=>{data=d;paint();})
 .catch(()=>{$('#body').innerHTML='<div class="empty">Не удалось загрузить расписание.</div>';});
"""


def app_page(title, slug_, name, mode):
    if mode == 't':
        back = '<a href="../prep.html">← преподаватели</a>'
    else:
        back = '<a href="../index.html">← все группы</a>'
    body = ('<div class="sub">%s</div>'
            '<h1>%s</h1><div id="tabs" class="tabs"></div><div id="body">'
            '<div class="empty">Загрузка…</div></div>' % (back, html.escape(name)))
    js = '<script>%s</script>' % (APP_JS % (slug_, name.replace("'", "\\'"), mode))
    return page(title, body + js)


def prep_index(teachers):
    items = sorted(teachers)
    rows = ['<a class="chip" data-n="%s" href="p/%s.html">%s</a>'
            % (html.escape(t.lower()), slug(t), html.escape(t)) for t in items]
    body = ('<h1>Преподаватели</h1><div class="sub">Всего: %d · выберите, чтобы открыть расписание</div>'
            '<input class="q" id="q" placeholder="Фамилия, например Коваль" autocomplete="off">'
            '<div class="chips" id="list">%s</div>'
            '<p><a href="index.html">← всё расписание</a></p>'
            '<script>var q=document.getElementById("q"),l=document.getElementById("list");'
            'q.addEventListener("input",function(){var v=q.value.toLowerCase().trim();'
            'Array.prototype.forEach.call(l.children,function(a){'
            'a.style.display=a.dataset.n.indexOf(v)>-1?"":"none";});});</script>'
            % (len(items), ''.join(rows)))
    return page('Преподаватели', body)


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
