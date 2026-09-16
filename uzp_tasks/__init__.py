"""Отчёт об эффективности отработки задач воронки (привлечение, расширение,
запуск, активация).

Точка входа — run(): её и вызывает тетрадка. Вся логика в модулях рядом,
в ячейках тетрадки только параметры и вызов (правило 1).

Что получается на выходе:
  output/tasks_dashboard_<месяц>.html   — дэшборд с выбором ТБ
  output/tasks_employees_<месяц>.csv    — сотрудники: результат, дисциплина, риск
  output/tasks_clients_<месяц>.csv      — клиенты: комплексная отработка
  output/tasks_gosb_<месяц>.csv         — свод по ГОСБ
  output/tasks_tb_<месяц>.csv           — свод по ТБ
  output/tasks_recommendations_<месяц>.csv — рекомендации
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import analysis, config, queries, recommend, report
from .db import get_engine, guard_rows, ping, read_sql
from .progress import done, num, step, warn

__all__ = ["run", "compute"]

LIMITS = [
    "Цифровой след ограничен событиями воронки: закрытие задачи, "
    "зафиксированная активность (звонок, встреча), заведение сделки. "
    "Работа в других системах в этой витрине не видна.",
    "Рабочими днями считаются будни: производственного календаря в витринах "
    "канала нет, поэтому праздники попадают в знаменатель «немых дней». "
    "Для сравнения сотрудников между собой поправка одинакова.",
    "Время постановки задачи в витрине — дата без часов, поэтому цикл "
    "отработки считается в днях от начала дня постановки; закрытие в день "
    "постановки даёт цикл 0.",
    "Одна задача живёт в нескольких месячных снимках витрины; берётся "
    "последнее состояние задачи на дату среза.",
    "Успех определяется флагом витрины is_task_closed_success; «успех без "
    "результата» — это успех с фактом получателей не выше 1 либо не выше "
    "10 % плана.",
]


def month_bounds(month: str) -> tuple[date, date]:
    """'2026-08' -> (2026-08-01, 2026-08-31)."""
    try:
        p = pd.Period(month, freq="M")
    except Exception as ex:
        raise ValueError(
            f"Отчётный месяц задаётся строкой вида '2026-08', получено {month!r}"
        ) from ex
    return p.start_time.date(), p.end_time.date()


def _probe(engine, schema: str) -> None:
    """Разведка витрины ДО долгого прогона: на месте ли колонки.

    На проме отладиться негде, а самые дорогие отказы — самые глупые:
    колонка называется иначе, и прогон падает на двадцатой минуте.
    """
    cols = read_sql(engine, queries.PROBE_COLUMNS, {"schema": schema}, schema=schema)
    if cols.empty:
        raise RuntimeError(
            f"В схеме {schema} не видно таблицы uzp_dwh_sale_funnel_task. "
            f"Проверьте схему и права доступа.")
    have = set(cols["column_name"])
    need = queries.REQUIRED_COLUMNS["uzp_dwh_sale_funnel_task"]
    missing = sorted(set(need) - have)
    if missing:
        raise RuntimeError(
            f"В uzp_dwh_sale_funnel_task не хватает колонок: {missing}")
    done(f"витрина на месте: {len(have)} колонок, все нужные есть")


def _pick_as_of(engine, schema: str, month_end: date, as_of: str) -> date:
    """Дата среза: явная из тетрадки либо последний снимок витрины.

    Автовыбор сопровождается предупреждением (правило 22): взятый снимок
    определяет, какую часть отработки мы вообще видим, и молча подменять его
    нельзя.
    """
    snaps = read_sql(engine, queries.SNAPSHOTS, {"dt_from": str(month_end)},
                     schema=schema)
    if snaps.empty:
        raise RuntimeError(
            f"В витрине нет ни одного снимка report_dt на {month_end} и позже. "
            f"report_dt — это КОНЕЦ месяца: отчётный месяц ещё не загружен.")
    available = [pd.Timestamp(d).date() for d in snaps["report_dt"]]
    for row in snaps.itertuples():
        done(f"снимок {row.report_dt}: {num(row.rows_qty)} строк")

    if as_of:
        want = pd.Timestamp(as_of).date()
        if want not in available:
            raise RuntimeError(
                f"Снимка {want} в витрине нет. Доступны: "
                f"{', '.join(str(d) for d in available)}")
        return want

    picked = max(available)
    warn(f"дата среза не задана — взят последний снимок витрины {picked}. "
         f"Задайте as_of в тетрадке, если нужен другой.")
    return picked


def compute(engine, month: str, as_of: str = "",
            task_types=config.TARGET_TASK_TYPES,
            subtype_like: str = config.TARGET_SUBTYPE_LIKE,
            schema: str | None = None) -> dict:
    """Посчитать все срезы отчёта. Без записи на диск."""
    schema = schema or config.SCHEMA
    dt_from, dt_to = month_bounds(month)

    step(f"разведка витрины и снимков (отчётный месяц {month})")
    _probe(engine, schema)
    as_of_dt = _pick_as_of(engine, schema, dt_to, as_of)

    params = {"snap_from": str(dt_to), "as_of": str(as_of_dt),
              "dt_from": str(dt_from), "dt_to": str(dt_to),
              "subtype_like": subtype_like}

    step(f"задачи, выставленные с {dt_from} по {dt_to}")
    tasks = read_sql(engine, queries.with_types(queries.TASKS, task_types),
                     params, schema=schema)
    guard_rows(tasks, "задачи", "Сузьте список типов задач или период.")
    if tasks.empty:
        raise RuntimeError(
            f"За {month} не найдено ни одной задачи типов {task_types}. "
            f"Проверьте месяц и названия типов в витрине.")
    done(f"задач: {num(len(tasks))} · клиентов {num(tasks['inn'].nunique())} · "
         f"сотрудников {num(tasks['emp_id'].nunique())}")

    step("цифровой след сотрудников по дням (все типы задач)")
    footprint = read_sql(engine, queries.FOOTPRINT, params, schema=schema)
    done(f"дней со следами: {num(len(footprint))}")

    step("потенциал численности клиентов")
    try:
        potential = read_sql(
            engine, queries.with_types(queries.POTENTIAL, task_types),
            params, schema=schema)
        done(f"потенциал известен по {num(len(potential))} клиентам")
    except Exception as ex:
        warn(f"потенциал не прочитан ({type(ex).__name__}), метрика «факт к "
             f"потенциалу» считаться не будет")
        potential = pd.DataFrame(columns=["inn", "emp_potential_qty"])

    step("признаки на задачах: сроки, следы, массовые закрытия, качество записей")
    t = analysis.enrich_tasks(tasks, as_of_dt, potential)
    done(f"в днях зачистки {num(t['burst_close'].sum())} закрытий · "
         f"в сериях по минутам {num(t['conveyor_close'].sum())}")

    step("свод по клиентам (комплексная отработка)")
    clients = analysis.by_client(t)
    done(f"клиентов {num(len(clients))} · полностью отработано "
         f"{num(clients['is_full'].sum())} · закрыто одним днём "
         f"{num(clients['sweep'].sum())}")

    step("свод по сотрудникам: результат, дисциплина, риск")
    emp = analysis.by_employee(t, clients, footprint, dt_from,
                              min(dt_to, as_of_dt))
    done(f"сотрудников {num(len(emp))} · под триггерами "
         f"{num((emp['flags_qty'] > 0).sum())}")

    step("своды по ГОСБ и ТБ")
    gosb = analysis.by_unit(t, emp, clients, ["tb_id", "tb_name", "gosb_id", "gosb_name"])
    tb = analysis.by_unit(t, emp, clients, ["tb_id", "tb_name"])
    done(f"ГОСБ {num(len(gosb))} · ТБ {num(len(tb))}")

    tt = analysis.totals(t, emp, clients)
    analysis.log_totals(tt)

    step("проверка сходимости")
    issues = analysis.check(t, emp, clients, tb)

    step("рекомендации по правилам")
    recs = recommend.system_recommendations(tt)
    tb_recs = recommend.tb_recommendations(tb, emp)
    emp = recommend.describe_flags(emp)
    done(f"рекомендаций: по системе {len(recs)} · адресных по ТБ {len(tb_recs)}")

    return {"tasks": t, "employees": emp,
            "clients": clients, "gosb": gosb, "tb": tb, "totals": tt,
            "issues": issues, "recs": recs, "tb_recs": tb_recs,
            "as_of": as_of_dt, "dt_from": dt_from, "dt_to": dt_to,
            "task_types": list(task_types)}


def run(conn: str | None = None,
        report_month: str = "",
        as_of: str = "",
        task_types=config.TARGET_TASK_TYPES,
        subtype_like: str = config.TARGET_SUBTYPE_LIKE,
        schema: str | None = None,
        out_dir: Path | None = None) -> dict:
    """Полный прогон: проверка соединения, расчёт, CSV и дэшборд.

    Отчётный месяц — ЯВНЫЙ параметр (правило 22). Автовыбор «последний месяц
    витрины» тихо сдвинул бы отчёт: запуск в середине месяца взял бы уже
    начавшийся месяц вместо закрытого, и увидеть это в результате нельзя.
    """
    if not report_month:
        raise ValueError(
            "Задайте отчётный месяц явно: report_month='2026-08' — месяц, "
            "в котором задачи были ВЫСТАВЛЕНЫ.")
    schema = schema or config.SCHEMA
    engine = get_engine(config.db_url(conn))

    step("проверка соединения с БД")
    ping(engine)
    done("соединение живо")

    res = compute(engine, report_month, as_of, task_types, subtype_like, schema)

    out_dir = Path(out_dir or config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    step("выгрузка таблиц")
    recs_df = pd.DataFrame(res["recs"] + res["tb_recs"])
    paths = report.write_csv({
        "employees": (res["employees"], report.EMP_COLUMNS),
        "clients": (res["clients"], report.CLIENT_COLUMNS),
        "gosb": (res["gosb"], report.UNIT_COLUMNS),
        "tb": (res["tb"], report.UNIT_COLUMNS),
        "recommendations": (recs_df, report.REC_COLUMNS),
    }, report_month, out_dir)

    step("дэшборд")
    meta = {
        "month": report_month,
        "dt_from": str(res["dt_from"]),
        "dt_to": str(res["dt_to"]),
        "as_of": str(res["as_of"]),
        "types": ", ".join(res["task_types"]) + f" + подтип «{subtype_like}»",
        "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "limits": LIMITS,
    }
    payload = report.build_payload(
        res["tasks"], res["employees"], res["clients"], res["tb"], res["gosb"],
        res["recs"], res["tb_recs"], meta, res["issues"], res["totals"])
    paths["dashboard"] = report.write_html(payload, report_month, out_dir)

    res["paths"] = paths
    return res
