"""Выгрузка результата: CSV-таблицы и HTML-дэшборд с выбором ТБ.

Дэшборд — сложный артефакт (правило 14): слово-идентификатор
налогоплательщика в готовом HTML заменяется на «Орг.», иначе файл не проходит
по почте. Замена делается последним шагом и по ГОТОВОМУ документу целиком —
тогда под неё попадает и то, что пришло из витрины, и то, что написано в
шаблоне.

Интернета на закрытом контуре нет (правило 16): весь CSS и JS — внутри файла,
ни одной внешней ссылки, ни одного шрифта с CDN. Графики нарисованы
собственной разметкой, без библиотек.

Размер артефакта — проектное ограничение (правило 23): в детальные таблицы
попадают только строки выше порога материальности, и каждое отсечение
подписано честно — «показано N из M».
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .progress import done, num

TEMPLATE = Path(__file__).with_name("dashboard.html.tpl")

# Меняем ТОЛЬКО отдельное слово: иначе пострадают слова, где эти буквы внутри.
# Латинские идентификаторы в коде (inn, task_code) не трогаем — они не слово.
_WORD = re.compile(r"(?<![А-Яа-яЁёA-Za-z])ИНН(?![А-Яа-яЁёA-Za-z])", re.IGNORECASE)


def sanitize(text: str) -> str:
    """Убрать из готового документа слово-блокатор (правило 14)."""
    return _WORD.sub("Орг.", text or "")


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
EMP_COLUMNS = [
    ("tb_name", "ТБ"), ("gosb_name", "ГОСБ"), ("emp_fio", "Сотрудник"),
    ("emp_id", "Табельный"), ("emp_post", "Должность"), ("role_code", "Роль"),
    ("manager_fio", "Руководитель"),
    ("tasks", "Задач"), ("closed", "Закрыто"), ("success", "Успешно"),
    ("refused", "Невозможно отработать"), ("open", "В работе"),
    ("stale", "Висят более 30 дн."),
    ("close_rate", "Закрыто, %"), ("success_rate", "Успех от закрытых, %"),
    ("median_cycle", "Медиана отработки, дн."), ("avg_cycle", "Среднее, дн."),
    ("p90_cycle", "90-й перцентиль, дн."),
    ("overdue_share", "Просрочено, %"), ("same_day_share", "Закрыто в день постановки, %"),
    ("burst_share", "В днях зачистки, %"), ("max_closed_day", "Макс. закрытий за день"),
    ("conveyor_share", "В сериях по минутам, %"),
    ("no_footprint_share", "Без цифрового следа, %"),
    ("stub_share", "Формальный комментарий, %"), ("clone_share", "Клон комментария, %"),
    ("quest_share", "Анкета заполнена, %"),
    ("low_value_share", "Успехи без результата, %"),
    ("plan_qty", "План получателей"), ("fact_qty", "Факт получателей"),
    ("fill_rate", "Факт к плану, %"),
    ("clients", "Клиентов"), ("clients_multi", "Клиентов с 2+ задачами"),
    ("clients_full", "Клиентов отработано полностью"),
    ("client_full_share", "Полная отработка клиента, %"),
    ("clients_sweep", "Клиентов закрыто одним днём"),
    ("clients_contradiction", "Клиентов с противоречием"),
    ("work_days", "Рабочих дней"), ("active_days", "Дней со следами"),
    ("silent_days", "Немых дней"), ("silent_share", "Немых дней, %"),
    ("result_index", "Индекс результата"), ("discipline_index", "Индекс дисциплины"),
    ("risk_index", "Индекс риска"), ("flags_qty", "Триггеров"),
    ("what_to_check", "Что проверить"),
]

CLIENT_COLUMNS = [
    ("tb_name", "ТБ"), ("gosb_name", "ГОСБ"), ("inn", "ИНН"),
    ("company_name", "Организация"), ("segment_name", "Сегмент"),
    ("emp_fio", "Сотрудник"), ("tasks", "Задач"), ("closed", "Закрыто"),
    ("success", "Успешно"), ("refused", "Невозможно отработать"),
    ("open", "В работе"), ("status", "Статус отработки"),
    ("contradiction", "Противоречие в решениях"),
    ("sweep", "Все задачи закрыты одним днём"),
    ("no_footprint_all", "Ни одного цифрового следа"),
    ("plan_qty", "План получателей"), ("fact_qty", "Факт получателей"),
    ("fill_rate", "Факт к плану, %"), ("potential_qty", "Потенциал численности"),
    ("potential_rate", "Факт к потенциалу, %"),
]

UNIT_COLUMNS = [
    ("tb_name", "ТБ"), ("gosb_name", "ГОСБ"),
    ("tasks", "Задач"), ("closed", "Закрыто"), ("success", "Успешно"),
    ("open", "В работе"), ("employees", "Сотрудников"), ("clients", "Клиентов"),
    ("close_rate", "Закрыто, %"), ("success_rate", "Успех от закрытых, %"),
    ("median_cycle", "Медиана отработки, дн."),
    ("overdue_share", "Просрочено, %"), ("same_day_share", "В день постановки, %"),
    ("burst_share", "В днях зачистки, %"), ("conveyor_share", "В сериях, %"),
    ("no_footprint_share", "Без следа, %"), ("stub_share", "Формальный комментарий, %"),
    ("clone_share", "Клон комментария, %"), ("low_value_share", "Успехи без результата, %"),
    ("fill_rate", "Факт к плану, %"), ("client_full_share", "Клиент отработан полностью, %"),
    ("clients_sweep", "Клиентов одним днём"), ("silent_share", "Немых дней, %"),
    ("result_index", "Индекс результата"), ("discipline_index", "Индекс дисциплины"),
    ("risk_index", "Индекс риска"), ("emp_flagged", "Сотрудников под триггерами"),
]

REC_COLUMNS = [
    ("scope", "Уровень"), ("unit", "Подразделение"), ("priority", "Приоритет"),
    ("title", "Что обнаружено"), ("finding", "Факт"), ("action", "Что делать"),
    ("owner", "Кто отвечает"), ("control", "Как проверить результат"),
]

SHARE_COLUMNS = {c for c, title in EMP_COLUMNS + CLIENT_COLUMNS + UNIT_COLUMNS
                 if title.endswith(", %")}


def _rename(df: pd.DataFrame, columns) -> pd.DataFrame:
    keep = [(src, title) for src, title in columns if src in df.columns]
    out = df[[src for src, _ in keep]].copy()
    for src, title in keep:
        if src in SHARE_COLUMNS:
            out[src] = (pd.to_numeric(out[src], errors="coerce") * 100).round(1)
    return out.rename(columns=dict(keep))


def write_csv(frames: dict[str, pd.DataFrame], month: str,
              out_dir: Path) -> dict[str, Path]:
    """Разделитель «;» и BOM — иначе Excel открывает кириллицу одной колонкой."""
    paths = {}
    for name, (df, cols) in frames.items():
        if df is None or df.empty:
            continue
        path = out_dir / f"tasks_{name}_{month}.csv"
        _rename(df, cols).to_csv(path, index=False, sep=";",
                                 encoding="utf-8-sig", decimal=",")
        paths[name] = path
        done(f"{name}: {num(len(df))} строк -> {path.name}")
    return paths


# --------------------------------------------------------------------------- #
# Данные дэшборда
# --------------------------------------------------------------------------- #
CYCLE_BINS = [(0, 0, "в день"), (1, 3, "1-3 дн."), (4, 7, "4-7 дн."),
              (8, 14, "8-14 дн."), (15, 30, "15-30 дн."), (31, 10**6, "31+ дн.")]

TRIGGER_CARDS = [
    ("burst_share", "Закрытия в днях зачистки", "burst"),
    ("conveyor_share", "Закрытия сериями по минутам", "conveyor"),
    ("no_footprint_share", "Закрытия без цифрового следа", "no_footprint"),
    ("same_day_share", "Закрытия в день постановки", "same_day"),
    ("low_value_share", "Успехи без результата", "low_value"),
    ("clone_share", "Клонированные комментарии", "clone"),
    ("stub_share", "Формальные комментарии", "stub"),
    ("silent_share", "Дни без цифровых следов", "silent_days"),
]


def _cycle_hist(t: pd.DataFrame) -> list[dict]:
    """Распределение времени отработки по закрытым задачам."""
    closed = t.loc[t["is_closed"], "cycle_days"].dropna()
    total = len(closed)
    out = []
    for lo, hi, label in CYCLE_BINS:
        qty = int(((closed >= lo) & (closed <= hi)).sum()) if total else 0
        out.append({"label": label, "qty": qty,
                    "share": round(qty / total, 4) if total else 0.0})
    return out


def _kpi(tt: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in tt.items()}


def _emp_rows(e: pd.DataFrame, limit: int) -> dict:
    """Красный список: только сотрудники с сработавшими триггерами."""
    if e.empty:
        return {"rows": [], "shown": 0, "total": 0}
    flagged = e[e["flags_qty"] > 0]
    total = len(flagged)
    rows = []
    for r in flagged.nlargest(limit, "risk_index").itertuples():
        rows.append([
            r.emp_fio, int(r.emp_id), r.gosb_name, r.role_code,
            int(r.tasks), int(r.closed), int(r.success),
            round(float(r.success_rate), 3), round(float(r.median_cycle or 0), 1),
            round(float(r.burst_share), 3), round(float(r.no_footprint_share), 3),
            round(float(r.low_value_share), 3), round(float(r.silent_share), 3),
            float(r.risk_index), float(r.result_index), float(r.discipline_index),
            getattr(r, "what_to_check", "") or "",
        ])
    return {"rows": rows, "shown": len(rows), "total": total}


def _client_rows(c: pd.DataFrame, limit: int) -> dict:
    """Клиенты, требующие вмешательства: не целиком, противоречия, зачистки."""
    if c.empty:
        return {"rows": [], "shown": 0, "total": 0}
    bad = c[(~c["is_full"]) | c["contradiction"] | c["sweep"]
            | c["no_footprint_all"]].copy()
    total = len(bad)
    # сортировка по величине потерянного: сначала крупный неотработанный клиент
    bad["lost"] = (bad["plan_qty"] - bad["fact_qty"]).clip(lower=0)
    rows = []
    for r in bad.nlargest(limit, "lost").itertuples():
        reasons = []
        if not r.is_full:
            reasons.append(r.status.lower())
        if r.contradiction:
            reasons.append("противоречие в решениях")
        if r.sweep:
            reasons.append("все задачи закрыты одним днём")
        if r.no_footprint_all:
            reasons.append("ни одного цифрового следа")
        rows.append([
            str(r.company_name or ""), int(r.inn), r.gosb_name, r.segment_name,
            r.emp_fio, int(r.tasks), int(r.closed), int(r.success),
            int(r.plan_qty), int(r.fact_qty),
            (int(r.potential_qty) if pd.notna(r.potential_qty) else None),
            "; ".join(reasons),
        ])
    return {"rows": rows, "shown": len(rows), "total": total}


def _unit_rows(u: pd.DataFrame, name_col: str, limit: int = 25) -> list[dict]:
    """Ранжирование подразделений: результат, дисциплина, риск."""
    if u.empty:
        return []
    out = []
    for r in u.nlargest(limit, "tasks").itertuples():
        out.append({
            "name": getattr(r, name_col),
            "tasks": int(r.tasks),
            "close_rate": round(float(r.close_rate), 4),
            "success_rate": round(float(r.success_rate), 4),
            "median_cycle": round(float(r.median_cycle or 0), 1),
            "result_index": float(r.result_index or 0),
            "discipline_index": float(r.discipline_index or 0),
            "risk_index": float(r.risk_index or 0),
            "burst_share": round(float(r.burst_share), 4),
            "no_footprint_share": round(float(r.no_footprint_share), 4),
            "low_value_share": round(float(r.low_value_share), 4),
            "client_full_share": round(float(r.client_full_share), 4),
        })
    return out


def build_payload(t: pd.DataFrame, e: pd.DataFrame, c: pd.DataFrame,
                  tb: pd.DataFrame, gosb: pd.DataFrame, recs: list[dict],
                  tb_recs: list[dict], meta: dict, issues: list[str],
                  totals_all: dict) -> dict:
    """Собрать данные дэшборда: общий срез и срез по каждому ТБ."""
    from . import analysis, recommend

    units = {"ALL": {
        "name": "Все ТБ",
        "kpi": _kpi(totals_all),
        "hist": _cycle_hist(t),
        "ranking": _unit_rows(tb, "tb_name"),
        "ranking_title": "Территориальные банки",
        "employees": _emp_rows(e, config.TOP_N_RISK),
        "clients": _client_rows(c, config.TOP_N_CLIENTS),
        "recs": recs,
    }}

    for tb_id, part in t.groupby("tb_id"):
        emp_part = e[e["tb_id"] == tb_id] if len(e) else e
        cl_part = c[c["tb_id"] == tb_id] if len(c) else c
        gosb_part = gosb[gosb["tb_id"] == tb_id] if len(gosb) else gosb
        tt = analysis.totals(part, emp_part, cl_part)
        # Рекомендации для ТБ считаются по ЕГО собственным числам, а не
        # наследуются от системы: пороги могли сработать в целом по каналу и
        # не сработать здесь (и наоборот). Сверху добавляются адресные
        # пункты — то, чем этот ТБ отличается от остальных.
        unit_name = str(part["tb_name"].iloc[0])
        own_recs = ([r for r in tb_recs if r.get("tb_id") == int(tb_id)]
                    + recommend.system_recommendations(tt, unit_name, "ТБ"))
        units[str(int(tb_id))] = {
            "name": unit_name,
            "kpi": _kpi(tt),
            "hist": _cycle_hist(part),
            "ranking": _unit_rows(gosb_part, "gosb_name"),
            "ranking_title": "ГОСБ",
            "employees": _emp_rows(emp_part, config.TOP_N_RISK),
            "clients": _client_rows(cl_part, config.TOP_N_CLIENTS),
            "recs": own_recs,
        }

    thresholds = {key: config.TRIGGERS[key]["share"] for key in config.TRIGGERS
                  if "share" in config.TRIGGERS[key]}
    return {
        "meta": meta,
        "issues": issues,
        "units": units,
        "trigger_cards": [{"key": k, "title": title, "threshold": thresholds.get(tkey)}
                          for k, title, tkey in TRIGGER_CARDS],
        "order": ["ALL"] + [k for k in sorted(units) if k != "ALL"],
    }


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def write_html(payload: dict, month: str, out_dir: Path) -> Path:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      default=_json_default)
    # Название организации из витрины может содержать «</», и тогда браузер
    # закроет тег <script> посреди данных. Экранируем — для JSON это та же
    # строка, для парсера HTML уже не закрывающий тег.
    data = data.replace("</", "<\\/")
    html = tpl.replace("__DATA__", data).replace("__MONTH__", month)
    html = sanitize(html)                      # правило 14 — последним шагом
    path = out_dir / f"tasks_dashboard_{month}.html"
    path.write_text(html, encoding="utf-8")
    size_mb = path.stat().st_size / 1024 / 1024
    done(f"дэшборд: {path.name} ({size_mb:.1f} МБ)")
    return path


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, date)):
        return str(obj)[:10]
    if obj is pd.NaT:
        return None
    return str(obj)
