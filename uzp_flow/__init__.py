"""Отчёт о перетоке ФЛ между ИНН: год к году по зарплатным зачислениям.

Точка входа — run(): её и вызывает тетрадка. Вся логика в модулях рядом,
в ячейках тетрадки только параметры и вызов (правило 1).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import analysis, config, queries, report
from .db import get_engine, guard_rows, ping, probe, read_sql
from .progress import done, step

__all__ = ["run", "compute"]


def _month_label(dt: str) -> str:
    """Ярлык месяца для заголовков и имён файлов: '2026-08-31' -> '2026-08'."""
    return str(dt)[:7]


def compute(engine, base_dt: str, rep_dt: str,
            codes=config.PAYROLL_CODES,
            amt_min: int = config.AMT_MIN,
            min_qty: int = config.MIN_QTY,
            mass_min_qty: int = config.MASS_MIN_QTY,
            mass_min_share: float = config.MASS_MIN_SHARE,
            top_n: int = 3,
            schema: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Посчитать итоговую таблицу и направления перетока. Без записи на диск."""
    params = {"base_dt": base_dt, "rep_dt": rep_dt, "amt_min": amt_min,
              "min_qty": min_qty}

    step(f"портфели и переток: {base_dt} -> {rep_dt}")
    summary = read_sql(engine, queries.with_codes(queries.SUMMARY, codes),
                       params, schema=schema)
    guard_rows(summary, "итоговая таблица",
               "Поднимите порог материальности min_qty.")
    done(f"итоговая таблица: {len(summary):,} строк (ТБ+ГОСБ+ИНН)"
         .replace(",", " "))

    step(f"направления перетока: до {top_n} приёмников на организацию")
    edges = read_sql(engine, queries.with_codes(queries.EDGES, codes),
                     dict(params, top_n=top_n), schema=schema)
    guard_rows(edges, "направления перетока", "Уменьшите top_n.")
    done(f"направлений перетока: {len(edges):,}".replace(",", " "))

    summary = analysis.classify(summary, mass_min_qty, mass_min_share)
    analysis.check(summary)
    summary = summary.sort_values(
        ["flow_out_qty", "real_loss_qty", "base_qty"], ascending=False)
    return summary, edges


def run(conn: str | None = None,
        base_dt: str = "",
        rep_dt: str = "",
        schema: str | None = None,
        codes=config.PAYROLL_CODES,
        amt_min: int = config.AMT_MIN,
        min_qty: int = config.MIN_QTY,
        mass_min_qty: int = config.MASS_MIN_QTY,
        mass_min_share: float = config.MASS_MIN_SHARE,
        top_n: int = 3,
        out_dir: Path | None = None) -> dict:
    """Полный прогон: проверка соединения, разведка витрины, расчёт, выгрузка.

    Оба месяца — ЯВНЫЕ параметры (правило 22). Автовыбор «последний месяц
    витрины» тихо сдвинул бы отчёт: запуск 3-го числа взял бы уже начавшийся
    месяц вместо закрытого, и увидеть это в результате нельзя.
    """
    if not base_dt or not rep_dt:
        raise ValueError(
            "Задайте оба месяца явно: base_dt и rep_dt — последний день месяца, "
            "например base_dt='2025-08-31', rep_dt='2026-08-31'"
        )
    schema = schema or config.SCHEMA
    engine = get_engine(config.db_url(conn))

    step("проверка соединения с БД")
    ping(engine)
    done("соединение живо")

    step("разведка витрины: колонки и оба месяца")
    months = probe(engine, base_dt, rep_dt, schema=schema)
    for row in months.itertuples():
        done(f"{row.report_dt}: {row.rows_qty:,} строк ведомостей"
             .replace(",", " "))

    summary, edges = compute(engine, base_dt, rep_dt, codes, amt_min, min_qty,
                             mass_min_qty, mass_min_share, top_n, schema)

    t = analysis.totals(summary)
    analysis.log_totals(t)

    paths = report.write(summary, edges, _month_label(base_dt),
                         _month_label(rep_dt), out_dir)
    return {"paths": paths, "totals": t, "summary": summary, "edges": edges}
