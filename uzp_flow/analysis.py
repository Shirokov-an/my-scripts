"""Разбор перетока ФЛ между ИНН: классификация, ротация, сходимость.

Тяжёлое сделано в SQL — сюда приезжает уже агрегат по (ТБ, ГОСБ, ИНН), и здесь
остаются только производные колонки и проверки.
"""
from __future__ import annotations

import pandas as pd

from . import config
from .progress import done, step, warn

FLOW_MASS = "массовый переход"
FLOW_ROTATION = "ротация"
FLOW_NONE = ""


def num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    """Числовая колонка или колонка из значений по умолчанию — ВСЕГДА Series.

    У отсутствующей колонки .get() возвращает скаляр nan, и следующий .fillna()
    падает с AttributeError. Ловушка стоила прогона уже после того, как код
    «работал».
    """
    if col in df:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype="float64")


def classify(summary: pd.DataFrame,
             mass_min_qty: int = config.MASS_MIN_QTY,
             mass_min_share: float = config.MASS_MIN_SHARE) -> pd.DataFrame:
    """Достроить производные метрики и признак массовости перетока.

    Массовый переход отличается от ротации ДВУМЯ условиями сразу: и абсолютным
    числом ушедших в один ИНН, и их долей в портфеле. Одного условия мало —
    12 человек из 3000 это ротация, а 12 из 15 переезд организации.
    """
    d = summary.copy()
    base = num(d, "base_qty")
    rep = num(d, "rep_qty")
    out = num(d, "out_qty")
    inq = num(d, "in_qty")
    flow = num(d, "flow_out_qty")
    top = num(d, "inn_to_qty")

    d["delta_qty"] = (rep - base).astype("int64")
    # Реальная потеря — НЕТТО: ротация гоняет людей в обе стороны, а интересует
    # изменение общего количества, а не судьба отдельных людей.
    d["real_loss_qty"] = (base - rep).clip(lower=0).astype("int64")
    # Сколько из реальной потери объяснено перетоком. Минимум, а не сумма:
    # перетёкших может быть больше нетто-потери, если параллельно шёл приток.
    d["loss_by_flow_qty"] = (pd.concat([d["real_loss_qty"], flow], axis=1)
                             .min(axis=1).astype("int64"))

    # Доли ротации считаются от портфеля БАЗОВОГО месяца — от той численности,
    # которая за год и обновлялась. У нулевого портфеля доля не определена.
    denom = base.where(base > 0)
    d["out_rate"] = (out / denom * 100).round(1)
    d["in_rate"] = (inq / denom * 100).round(1)
    d["flow_rate"] = (flow / denom * 100).round(1)

    share = (top / denom).fillna(0)
    d["flow_kind"] = FLOW_NONE
    d.loc[flow > 0, "flow_kind"] = FLOW_ROTATION
    d.loc[(top >= mass_min_qty) & (share >= mass_min_share), "flow_kind"] = FLOW_MASS

    d["inn_to"] = d["inn_to"].where(flow > 0)
    d["inn_to_name"] = d["inn_to_name"].where(flow > 0, "")
    return d


def check(summary: pd.DataFrame) -> None:
    """Сходимость (правило 25). Расхождение печатается, а не прячется."""
    base = num(summary, "base_qty")
    rep = num(summary, "rep_qty")
    residual = base - num(summary, "out_qty") + num(summary, "in_qty") - rep
    bad = int((residual.abs() > 0).sum())
    if bad:
        warn(f"портфель не сходится в {bad} строках "
             f"(численность = база − ушли + пришли); максимум невязки "
             f"{residual.abs().max():.0f}")
    else:
        done("сходимость портфеля: численность = база − ушли + пришли, невязок нет")

    over = int((num(summary, "flow_out_qty") > num(summary, "out_qty")).sum())
    if over:
        warn(f"перетёкших больше, чем ушедших, в {over} строках — "
             f"проверьте грейн: переток считается по человеку, уход по четвёрке")
    else:
        done("перетёкшие не превышают ушедших ни в одной строке")

    gosb = int((num(summary, "gosb_out_qty")
                + num(summary, "flow_out_qty") > num(summary, "out_qty")).sum())
    if gosb:
        warn(f"переезд между ГОСБ и переток вместе превышают уход в {gosb} строках")
    else:
        done("переезд между ГОСБ и переток укладываются в число ушедших")


def totals(summary: pd.DataFrame) -> dict:
    """Итоги прогона — их печатает тетрадка и сверяет methodology.md."""
    d = summary
    return {
        "Строк (ТБ+ГОСБ+ИНН)": int(len(d)),
        "Численность базового месяца": int(num(d, "base_qty").sum()),
        "Численность отчётного месяца": int(num(d, "rep_qty").sum()),
        "Ушло ФЛ за год": int(num(d, "out_qty").sum()),
        "Пришло ФЛ за год": int(num(d, "in_qty").sum()),
        "Перетекло ФЛ в другие ИНН": int(num(d, "flow_out_qty").sum()),
        "Переехало между ГОСБ одного ИНН": int(num(d, "gosb_out_qty").sum()),
        "Организаций с массовым переходом": int((d["flow_kind"] == FLOW_MASS).sum()),
        "Организаций с ротацией": int((d["flow_kind"] == FLOW_ROTATION).sum()),
        "Реальная потеря ФЛ": int(num(d, "real_loss_qty").sum()),
    }


def log_totals(t: dict) -> None:
    step("итоги прогона")
    for key, value in t.items():
        print(f"      {key:38s} {value:>12,}".replace(",", " "), flush=True)
