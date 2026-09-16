<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отработка задач воронки — __MONTH__</title>
<!--
  Артефакт открывается на машине без сети (правило 16): ни одной внешней
  ссылки, весь CSS и JS внутри файла, графики нарисованы разметкой.
  Палитра — валидированная референсная: слоты 1-3 категориальные,
  отдельные статусные цвета, которые никогда не используются как серии.
-->
<style>
:root {
  --surface: #fcfcfb;
  --plane: #f9f9f7;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --s1: #2a78d6;
  --s2: #eb6834;
  --s3: #1baf7a;
  --good: #0ca30c;
  --warning: #fab219;
  --serious: #ec835a;
  --critical: #d03b3b;
  --good-text: #006300;
  color-scheme: light;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--plane);
  color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1280px; margin: 0 auto; padding: 24px 16px 64px; }
header.top { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;
  justify-content: space-between; margin-bottom: 8px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: var(--ink-2); font-size: 13px; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  padding: 12px 0 20px; border-bottom: 1px solid var(--grid); margin-bottom: 24px; }
label.fl { font-size: 13px; color: var(--ink-2); }
select {
  font: inherit; padding: 7px 10px; border-radius: 8px; background: var(--surface);
  border: 1px solid var(--axis); color: var(--ink); min-width: 240px;
}
section { margin: 32px 0; }
h2 { font-size: 16px; margin: 0 0 4px; }
h2 + .note { color: var(--ink-2); font-size: 13px; margin: 0 0 16px; }
.note { color: var(--ink-2); font-size: 13px; }

/* --- плитки --- */
.tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; }
.tile .k { font-size: 12px; color: var(--ink-2); margin-bottom: 6px; }
.tile .v { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
.tile .d { font-size: 12px; color: var(--muted); margin-top: 4px; }
.tile.alarm .v { color: var(--critical); }
.tile.ok .v { color: var(--good-text); }

/* --- бар-чарты --- */
.chart { background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 18px 12px; }
.cols { display: grid; gap: 20px; grid-template-columns: 1fr 1fr; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }

.hist { display: flex; align-items: flex-end; gap: 10px; height: 200px;
  padding: 8px 0 0; border-bottom: 1px solid var(--axis); }
.hist .col { flex: 1; display: flex; flex-direction: column; justify-content: flex-end;
  align-items: center; height: 100%; cursor: default; }
.hist .bar { width: 100%; background: var(--s1); border-radius: 4px 4px 0 0;
  min-height: 2px; transition: opacity .12s; }
.hist .col:hover .bar { opacity: .78; }
.hist .val { font-size: 12px; color: var(--ink-2); margin-bottom: 4px;
  font-variant-numeric: tabular-nums; }
.hist-x { display: flex; gap: 10px; padding-top: 6px; }
.hist-x div { flex: 1; text-align: center; font-size: 11px; color: var(--muted); }

.rank { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.rank .row { display: grid; grid-template-columns: 180px 1fr 64px; gap: 10px;
  align-items: center; }
.rank .nm { font-size: 12px; color: var(--ink-2); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.rank .track { background: var(--plane); border-radius: 4px; height: 14px; position: relative; }
.rank .fill { height: 100%; border-radius: 4px; background: var(--s1); }
.rank .fill.warn { background: var(--s2); }
.rank .num { font-size: 12px; text-align: right; font-variant-numeric: tabular-nums;
  color: var(--ink); }

/* --- триггеры --- */
.trigs { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.trig { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; }
.trig .t { font-size: 13px; margin-bottom: 8px; display: flex; justify-content: space-between;
  gap: 8px; align-items: baseline; }
.trig .t b { font-size: 18px; font-variant-numeric: tabular-nums; font-weight: 600; }
.trig .track { position: relative; height: 10px; background: var(--plane);
  border-radius: 5px; overflow: visible; }
.trig .fill { height: 100%; border-radius: 5px; background: var(--s1); }
.trig .fill.over { background: var(--critical); }
.trig .mark { position: absolute; top: -3px; width: 2px; height: 16px; background: var(--axis); }
.trig .legend { font-size: 11px; color: var(--muted); margin-top: 8px; }
.badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px;
  padding: 1px 7px; border-radius: 999px; border: 1px solid var(--border); }
.badge.crit { color: var(--critical); border-color: var(--critical); }
.badge.ok { color: var(--good-text); border-color: var(--good); }

/* --- таблицы --- */
.tbl-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--grid);
  white-space: nowrap; }
th { font-size: 12px; color: var(--ink-2); font-weight: 600; cursor: pointer;
  position: sticky; top: 0; background: var(--surface); }
th:hover { color: var(--ink); }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }
td.wrap-txt { white-space: normal; min-width: 260px; color: var(--ink-2); }
.risk-hi { color: var(--critical); font-weight: 600; }
.risk-md { color: var(--serious); }

/* --- рекомендации --- */
.recs { display: flex; flex-direction: column; gap: 12px; }
.rec { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; border-left: 3px solid var(--axis); }
.rec.p1 { border-left-color: var(--critical); }
.rec.p2 { border-left-color: var(--warning); }
.rec.p3 { border-left-color: var(--s3); }
.rec h3 { font-size: 14px; margin: 0 0 6px; }
.rec p { margin: 4px 0; font-size: 13px; color: var(--ink-2); }
.rec .lbl { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: .04em; margin-right: 6px; }
.issues { background: #fdf3e7; border: 1px solid var(--serious); border-radius: 10px;
  padding: 12px 16px; font-size: 13px; color: var(--ink-2); margin: 16px 0; }
footer { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--grid);
  font-size: 12px; color: var(--muted); }
footer h3 { font-size: 13px; color: var(--ink-2); margin: 16px 0 6px; }
footer ul { margin: 4px 0; padding-left: 18px; }
.tip { position: fixed; pointer-events: none; z-index: 20; background: var(--ink);
  color: #fff; font-size: 12px; padding: 6px 9px; border-radius: 6px; opacity: 0;
  transition: opacity .1s; max-width: 280px; }
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <div>
    <h1>Отработка задач: привлечение, расширение, запуск, активация</h1>
    <div class="sub" id="meta"></div>
  </div>
  <div class="sub" id="asof"></div>
</header>

<div class="filters">
  <label class="fl" for="tb">Территориальный банк</label>
  <select id="tb"></select>
  <span class="sub" id="scope-note"></span>
</div>

<div id="issues"></div>

<section>
  <h2>Результат отработки</h2>
  <p class="note">Задачи, выставленные в отчётном месяце, по состоянию на дату среза.
     Клиент считается отработанным полностью, только если закрыты все его задачи.</p>
  <div class="tiles" id="kpi"></div>
</section>

<section class="cols">
  <div>
    <h2>Сколько времени занимает отработка</h2>
    <p class="note">Закрытые задачи по времени от постановки до закрытия.
       Столбец «в день» — закрытые в день постановки.</p>
    <div class="chart">
      <div class="hist" id="hist"></div>
      <div class="hist-x" id="hist-x"></div>
    </div>
  </div>
  <div>
    <h2 id="rank-title">Подразделения</h2>
    <p class="note">Индекс результата 0-100: конверсия, факт к плану получателей,
       доля полностью отработанных клиентов. Оранжевым — где индекс риска выше 50.</p>
    <div class="chart">
      <div class="rank" id="rank"></div>
    </div>
  </div>
</section>

<section>
  <h2>Триггеры достоверности и дисциплины</h2>
  <p class="note">Засечкой отмечен порог срабатывания триггера. Превышение —
     не обвинение, а приоритет ручной проверки.</p>
  <div class="trigs" id="trigs"></div>
</section>

<section>
  <h2>Сотрудники под триггерами</h2>
  <p class="note" id="emp-note"></p>
  <div class="tbl-wrap"><table id="emp"></table></div>
</section>

<section>
  <h2>Клиенты, требующие вмешательства</h2>
  <p class="note" id="cl-note"></p>
  <div class="tbl-wrap"><table id="cl"></table></div>
</section>

<section>
  <h2>Что делать</h2>
  <p class="note">Рекомендации формируются правилами по сработавшим порогам:
     что обнаружено, что делать, кто отвечает и по какому показателю проверять результат.</p>
  <div class="recs" id="recs"></div>
</section>

<footer>
  <div>Методика расчёта, формулы и ограничения — в <b>methodology_tasks.md</b>.
     Детальные выгрузки — CSV рядом с этим файлом.</div>
  <h3>Как читать индексы</h3>
  <ul>
    <li><b>Индекс результата</b> — 40 % конверсия успеха, 30 % факт к плану получателей,
        30 % доля клиентов, отработанных полностью.</li>
    <li><b>Индекс дисциплины</b> — 30 % отсутствие просрочки, 25 % присутствие в системе,
        25 % содержательность записей, 20 % скорость отработки.</li>
    <li><b>Индекс риска</b> — 100 баллов означает, что все шесть признаков манипуляции
        находятся на пороге срабатывания. При выборке меньше 10 закрытых задач
        индекс уменьшается вдвое: на малом числе наблюдений доли недостоверны.</li>
  </ul>
  <h3>Ограничения</h3>
  <ul id="limits"></ul>
</footer>

</div>
<div class="tip" id="tip"></div>

<script>
const DATA = __DATA__;
const tip = document.getElementById('tip');

/* Значения приходят из витрины: название организации может содержать «<» или
   «&», и без экранирования такая строка сломала бы разметку таблицы. */
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function pct(x, digits) { return (100 * (x || 0)).toFixed(digits === undefined ? 1 : digits) + '%'; }
function n(x) { return (x === null || x === undefined) ? '—' : Math.round(x).toLocaleString('ru-RU'); }
function f1(x) { return (x === null || x === undefined) ? '—' : Number(x).toFixed(1); }

function showTip(e, html) {
  tip.innerHTML = html;
  tip.style.opacity = '1';
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + 300 > window.innerWidth) x = e.clientX - 300;
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}
function hideTip() { tip.style.opacity = '0'; }

/* ---------- фильтр ТБ ---------- */
const sel = document.getElementById('tb');
DATA.order.forEach(function (key) {
  const o = document.createElement('option');
  o.value = key;
  o.textContent = DATA.units[key].name;
  sel.appendChild(o);
});
sel.addEventListener('change', function () { render(sel.value); });

/* ---------- плитки ---------- */
const TILES = [
  { k: 'Задач выставлено', get: d => n(d.tasks), d: d => n(d.clients) + ' клиентов · ' + n(d.employees) + ' сотрудников' },
  { k: 'Закрыто', get: d => pct(d.close_rate), d: d => n(d.closed) + ' из ' + n(d.tasks) + ', в работе ' + n(d.open) },
  { k: 'Успех от закрытых', get: d => pct(d.success_rate), d: d => n(d.success) + ' успешных, отказных ' + n(d.refused) },
  { k: 'Медиана отработки', get: d => f1(d.median_cycle) + ' дн.', d: d => 'среднее ' + f1(d.avg_cycle) + ' дн., 90-й перцентиль ' + f1(d.p90_cycle) + ' дн.' },
  { k: 'Факт к плану получателей', get: d => pct(d.fill_rate), d: d => n(d.fact_qty) + ' из ' + n(d.plan_qty) + ' чел.' },
  { k: 'Клиент отработан полностью', get: d => pct(d.clients ? d.clients_full / d.clients : 0), d: d => n(d.clients_full) + ' из ' + n(d.clients) + ', с 2+ задачами ' + n(d.clients_multi) },
  { k: 'Сотрудников под триггерами', get: d => n(d.emp_flagged), d: d => 'из ' + n(d.employees) + ' работавших', alarm: d => d.employees && d.emp_flagged / d.employees > 0.2 },
  { k: 'Средний индекс риска', get: d => f1(d.risk_index), d: d => 'результат ' + f1(d.result_index) + ' · дисциплина ' + f1(d.discipline_index), alarm: d => d.risk_index >= 50 }
];

function renderKpi(d) {
  document.getElementById('kpi').innerHTML = TILES.map(function (t) {
    const cls = (t.alarm && t.alarm(d)) ? ' alarm' : '';
    return '<div class="tile' + cls + '"><div class="k">' + t.k + '</div>' +
      '<div class="v">' + t.get(d) + '</div><div class="d">' + t.d(d) + '</div></div>';
  }).join('');
}

/* ---------- гистограмма цикла ---------- */
function renderHist(hist) {
  const max = Math.max.apply(null, hist.map(h => h.qty).concat([1]));
  document.getElementById('hist').innerHTML = hist.map(function (h) {
    const hgt = Math.max(2, Math.round(100 * h.qty / max));
    return '<div class="col" data-t="' + h.label + ': ' + n(h.qty) + ' задач (' + pct(h.share) + ')">' +
      '<div class="val">' + pct(h.share, 0) + '</div>' +
      '<div class="bar" style="height:' + hgt + '%"></div></div>';
  }).join('');
  document.getElementById('hist-x').innerHTML = hist.map(h => '<div>' + h.label + '</div>').join('');
  document.querySelectorAll('#hist .col').forEach(function (el) {
    el.addEventListener('mousemove', e => showTip(e, el.dataset.t));
    el.addEventListener('mouseleave', hideTip);
  });
}

/* ---------- рейтинг подразделений ---------- */
function renderRank(unit) {
  document.getElementById('rank-title').textContent = unit.ranking_title;
  const rows = unit.ranking.slice().sort((a, b) => b.result_index - a.result_index);
  const max = 100;
  document.getElementById('rank').innerHTML = rows.map(function (r) {
    const w = Math.max(1, Math.round(100 * r.result_index / max));
    const cls = r.risk_index >= 50 ? ' warn' : '';
    const t = esc(r.name) + ' — индекс результата ' + f1(r.result_index) +
      ', дисциплина ' + f1(r.discipline_index) + ', риск ' + f1(r.risk_index) +
      '<br>задач ' + n(r.tasks) + ', закрыто ' + pct(r.close_rate) +
      ', успех ' + pct(r.success_rate) + ', медиана ' + f1(r.median_cycle) + ' дн.' +
      '<br>клиент отработан полностью ' + pct(r.client_full_share);
    return '<div class="row" data-t="' + t.replace(/"/g, '&quot;') + '">' +
      '<div class="nm">' + esc(r.name) + '</div>' +
      '<div class="track"><div class="fill' + cls + '" style="width:' + w + '%"></div></div>' +
      '<div class="num">' + f1(r.result_index) + '</div></div>';
  }).join('');
  document.querySelectorAll('#rank .row').forEach(function (el) {
    el.addEventListener('mousemove', e => showTip(e, el.dataset.t));
    el.addEventListener('mouseleave', hideTip);
  });
}

/* ---------- триггеры ---------- */
function renderTrigs(d) {
  document.getElementById('trigs').innerHTML = DATA.trigger_cards.map(function (c) {
    const v = d[c.key] || 0;
    const thr = c.threshold || 0.5;
    const over = v >= thr;
    const w = Math.min(100, Math.round(100 * v / Math.max(thr * 2, 0.0001)));
    const mark = Math.min(100, Math.round(100 * thr / Math.max(thr * 2, 0.0001)));
    return '<div class="trig"><div class="t"><span>' + c.title + '</span><b>' + pct(v) + '</b></div>' +
      '<div class="track"><div class="fill' + (over ? ' over' : '') + '" style="width:' + w + '%"></div>' +
      '<div class="mark" style="left:' + mark + '%"></div></div>' +
      '<div class="legend">' + (over
        ? '<span class="badge crit">▲ выше порога ' + pct(thr, 0) + '</span>'
        : '<span class="badge ok">✓ в норме, порог ' + pct(thr, 0) + '</span>') + '</div></div>';
  }).join('');
}

/* ---------- таблицы ---------- */
const EMP_HEAD = ['Сотрудник', 'Табельный', 'ГОСБ', 'Роль', 'Задач', 'Закрыто', 'Успешно',
  'Успех, %', 'Медиана, дн.', 'В днях зачистки, %', 'Без следа, %', 'Успехи без результата, %',
  'Немых дней, %', 'Риск', 'Результат', 'Дисциплина', 'Что проверить'];
const EMP_FMT = [null, n, null, null, n, n, n, pct, f1, pct, pct, pct, pct, f1, f1, f1, null];

const CL_HEAD = ['Организация', 'ИНН', 'ГОСБ', 'Сегмент', 'Сотрудник', 'Задач', 'Закрыто',
  'Успешно', 'План, чел.', 'Факт, чел.', 'Потенциал, чел.', 'Почему в списке'];
const CL_FMT = [null, null, null, null, null, n, n, n, n, n, n, null];

function renderTable(el, head, fmt, rows, numericFrom) {
  const thead = '<thead><tr>' + head.map(function (h, i) {
    return '<th class="' + (i >= numericFrom && i < head.length - 1 ? 'n' : '') + '" data-i="' + i + '">' + esc(h) + '</th>';
  }).join('') + '</tr></thead>';
  const tbody = '<tbody>' + rows.map(function (r) {
    return '<tr>' + r.map(function (v, i) {
      const isNum = i >= numericFrom && i < head.length - 1;
      let cls = isNum ? 'n' : (i === head.length - 1 ? 'wrap-txt' : '');
      let txt = (fmt[i] ? fmt[i](v) : (v === null || v === undefined ? '—' : esc(v)));
      if (head[i] === 'Риск' && v >= 60) cls += ' risk-hi';
      else if (head[i] === 'Риск' && v >= 40) cls += ' risk-md';
      return '<td class="' + cls + '">' + txt + '</td>';
    }).join('') + '</tr>';
  }).join('') + '</tbody>';
  el.innerHTML = thead + tbody;

  el.querySelectorAll('th').forEach(function (th) {
    th.addEventListener('click', function () {
      const i = +th.dataset.i;
      const dir = th.dataset.dir === 'asc' ? -1 : 1;
      el.querySelectorAll('th').forEach(x => x.removeAttribute('data-dir'));
      th.dataset.dir = dir === 1 ? 'asc' : 'desc';
      rows.sort(function (a, b) {
        const x = a[i], y = b[i];
        if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
        return String(x).localeCompare(String(y), 'ru') * dir;
      });
      renderTable(el, head, fmt, rows, numericFrom);
    });
  });
}

/* ---------- рекомендации ---------- */
function renderRecs(recs, unitName) {
  const el = document.getElementById('recs');
  if (!recs.length) {
    el.innerHTML = '<div class="rec p3"><h3>Порогов не превышено</h3>' +
      '<p>По ' + unitName + ' ни один триггер не сработал. Контроль — в обычном режиме.</p></div>';
    return;
  }
  el.innerHTML = recs.map(function (r) {
    return '<div class="rec p' + r.priority + '"><h3>' + esc(r.title) +
      ' <span class="badge">' + esc(r.scope) + ' · ' + esc(r.unit) + '</span></h3>' +
      '<p><span class="lbl">Факт</span>' + esc(r.finding) + '</p>' +
      '<p><span class="lbl">Действие</span>' + esc(r.action) + '</p>' +
      '<p><span class="lbl">Ответственный</span>' + esc(r.owner) +
      ' <span class="lbl" style="margin-left:12px">Контроль</span>' + esc(r.control) + '</p></div>';
  }).join('');
}

/* ---------- сборка ---------- */
function render(key) {
  const unit = DATA.units[key];
  const d = unit.kpi;
  renderKpi(d);
  renderHist(unit.hist);
  renderRank(unit);
  renderTrigs(d);

  document.getElementById('emp-note').textContent =
    'Показано ' + unit.employees.shown + ' из ' + unit.employees.total +
    ' сотрудников, у которых сработал хотя бы один триггер. Сортировка по индексу риска; ' +
    'заголовок столбца сортирует таблицу.';
  renderTable(document.getElementById('emp'), EMP_HEAD, EMP_FMT, unit.employees.rows, 4);

  document.getElementById('cl-note').textContent =
    'Показано ' + unit.clients.shown + ' из ' + unit.clients.total +
    ' клиентов с незакрытыми задачами, противоречиями в решениях или закрытием всех задач одним днём. ' +
    'Сортировка по недополученным получателям.';
  renderTable(document.getElementById('cl'), CL_HEAD, CL_FMT, unit.clients.rows, 5);

  renderRecs(unit.recs, unit.name);
  document.getElementById('scope-note').textContent =
    key === 'ALL' ? 'весь канал' : 'выбран один ТБ; блоки ниже пересчитаны';
}

/* ---------- шапка и подвал ---------- */
document.getElementById('meta').innerHTML =
  'Отчётный месяц <b>' + DATA.meta.month + '</b> · задачи, выставленные с ' +
  DATA.meta.dt_from + ' по ' + DATA.meta.dt_to + ' · типы: ' + DATA.meta.types;
document.getElementById('asof').innerHTML =
  'Состояние на срез витрины <b>' + DATA.meta.as_of + '</b><br>' +
  'сформировано ' + DATA.meta.generated;
document.getElementById('limits').innerHTML = DATA.meta.limits.map(l => '<li>' + l + '</li>').join('');

if (DATA.issues && DATA.issues.length) {
  document.getElementById('issues').innerHTML =
    '<div class="issues"><b>Проверка сходимости нашла расхождения:</b><ul>' +
    DATA.issues.map(i => '<li>' + i + '</li>').join('') + '</ul></div>';
}

render('ALL');
</script>
</body>
</html>
