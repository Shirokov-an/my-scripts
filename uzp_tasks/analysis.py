"""Метрики отработки задач: признаки на задаче, срезы по сотруднику, клиенту, ТБ.

Логика расчёта каждой метрики описана в methodology_tasks.md — здесь код,
там формулы, примеры с числами и известные ограничения.

Общий принцип: сначала на КАЖДОЙ задаче считаются простые булевы признаки
(закрыта в день постановки, без цифрового следа, в пачке массового закрытия,
успех с нулевым результатом), и только потом они сворачиваются в доли по
сотруднику, клиенту, ГОСБ и ТБ. Так любое число в дэшборде раскрывается до
конкретного перечня задач, а не остаётся «оценкой модели».
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config
from .progress import done, num, warn

EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"      # md5('') — пустой комментарий


# --------------------------------------------------------------------------- #
# Вспомогательное (правило 21: ловушки pandas)
# --------------------------------------------------------------------------- #
def num_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    """Числовая колонка или колонка из значений по умолчанию — всегда Series.

    У отсутствующей колонки .get() возвращает СКАЛЯР nan, и следующий
    .fillna() падает с AttributeError.
    """
    if col in df:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index, dtype="float64")


def _share(numerator, denominator) -> pd.Series:
    """Доля с безопасным нулевым знаменателем: 0/0 = 0, а не NaN и не деление."""
    n = pd.to_numeric(numerator, errors="coerce").fillna(0.0)
    d = pd.to_numeric(denominator, errors="coerce").fillna(0.0)
    return pd.Series(np.where(d > 0, n / d.where(d > 0, 1), 0.0), index=n.index)


def _clip01(x) -> pd.Series:
    return pd.Series(x).clip(0.0, 1.0)


def work_days(month_start: date, month_end: date) -> list[date]:
    """Рабочие дни месяца — будни.

    Производственный календарь в витринах канала отсутствует, поэтому
    праздники в будни считаются рабочими. Это завышает знаменатель «немых
    дней» на число праздников в месяце — ограничение описано в методологии;
    для сравнения сотрудников между собой оно одинаково для всех.
    """
    out, d = [], month_start
    while d <= month_end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------------------- #
# Шаг 1. Признаки на задаче
# --------------------------------------------------------------------------- #
def enrich_tasks(tasks: pd.DataFrame, as_of: date,
                 potential: pd.DataFrame | None = None) -> pd.DataFrame:
    """Добавить к задачам булевы признаки отработки и сроки."""
    t = tasks.copy()
    as_of_ts = pd.Timestamp(as_of) + pd.Timedelta(hours=23, minutes=59)

    for col in ("plan_close_task_dttm", "fact_close_task_dttm",
                "last_active_dttm", "deal_create_dttm"):
        t[col] = pd.to_datetime(t[col], errors="coerce")
    t["task_create_dt"] = pd.to_datetime(t["task_create_dt"], errors="coerce")

    t["is_closed"] = t["is_closed"].fillna(False).astype(bool)
    t["is_success"] = t["is_success"].fillna(False).astype(bool)
    t["is_refused"] = t["task_text_status"].fillna("").str.contains(
        "невозможно отработать")
    t["is_open"] = ~t["is_closed"]

    # --- сроки ---
    # Время постановки в витрине — дата без часов, поэтому цикл считается в
    # днях от начала дня постановки. Для задачи, закрытой в тот же день, это
    # даёт 0, а не «полдня»: округление в пользу сотрудника.
    t["cycle_days"] = (t["fact_close_task_dttm"] - t["task_create_dt"]
                       ).dt.total_seconds() / 86400.0
    t["neg_cycle"] = t["cycle_days"].notna() & (t["cycle_days"] < 0)
    t.loc[t["neg_cycle"], "cycle_days"] = 0.0
    t["age_days"] = np.where(
        t["is_closed"], np.nan,
        (as_of_ts - t["task_create_dt"]).dt.total_seconds() / 86400.0)

    t["same_day"] = (t["is_closed"]
                     & (t["fact_close_task_dttm"].dt.normalize()
                        == t["task_create_dt"].dt.normalize()))

    t["overdue_closed"] = (t["is_closed"] & t["plan_close_task_dttm"].notna()
                           & (t["fact_close_task_dttm"] > t["plan_close_task_dttm"]))
    t["overdue_days"] = np.where(
        t["overdue_closed"],
        (t["fact_close_task_dttm"] - t["plan_close_task_dttm"]
         ).dt.total_seconds() / 86400.0, np.nan)
    t["overdue_open"] = (t["is_open"] & t["plan_close_task_dttm"].notna()
                         & (t["plan_close_task_dttm"] < as_of_ts))
    t["no_plan_dt"] = t["plan_close_task_dttm"].isna()
    t["stale"] = t["is_open"] & (num_col(t, "age_days") >= config.STALE_DAYS)
    t["stale_hard"] = t["is_open"] & (num_col(t, "age_days") >= config.STALE_DAYS_HARD)

    # --- цифровой след ---
    t["has_active"] = t["last_active_dttm"].notna()
    t["no_footprint"] = t["is_closed"] & ~t["has_active"]
    t["active_after_close"] = (t["is_closed"] & t["has_active"]
                               & (t["last_active_dttm"] > t["fact_close_task_dttm"]))

    # --- качество администрирования ---
    t["comment_len"] = num_col(t, "comment_len")
    t["quest_len"] = num_col(t, "quest_len")
    t["no_comment"] = t["is_closed"] & (t["comment_len"] == 0)
    t["stub_comment"] = t["is_closed"] & (t["comment_len"] < config.STUB_COMMENT_LEN)
    t["quest_filled"] = t["quest_len"] > 0

    # Клон: один и тот же непустой комментарий у сотрудника N раз и больше.
    t["comment_hash"] = t["comment_hash"].fillna(EMPTY_MD5)
    real = t["is_closed"] & (t["comment_len"] > 0) & (t["comment_hash"] != EMPTY_MD5)
    rep = (t[real].groupby(["emp_id", "comment_hash"])["task_code"]
           .transform("size"))
    t["comment_repeats"] = 0
    t.loc[real, "comment_repeats"] = rep
    t["clone_comment"] = t["comment_repeats"] >= config.CLONE_MIN_REPEAT

    # --- результат ---
    t["plan_qty"] = num_col(t, "plan_qty")
    t["fact_qty"] = num_col(t, "fact_qty")
    t["fill_rate"] = _share(t["fact_qty"], t["plan_qty"])
    # План и факт по УСПЕШНЫМ задачам. Отношение факта к плану считается
    # только по ним: в знаменателе по всем задачам сидит план ещё не закрытых
    # и отказных — там факта нет и быть не должно, и общая доля превращается
    # в «сколько задач закрыто», а не «сколько получателей получили».
    t["plan_qty_success"] = np.where(t["is_success"], t["plan_qty"], 0.0)
    t["fact_qty_success"] = np.where(t["is_success"], t["fact_qty"], 0.0)
    t["low_value_success"] = (
        t["is_success"]
        & ((t["fact_qty"] <= config.LOW_VALUE_FACT_QTY)
           | ((t["plan_qty"] > 0) & (t["fill_rate"] <= config.LOW_VALUE_FILL_RATE))))

    if potential is not None and len(potential):
        t = t.merge(potential, on="inn", how="left")
    t["emp_potential_qty"] = num_col(t, "emp_potential_qty", np.nan)

    # --- массовые закрытия и конвейер ---
    t = _mark_burst(t)
    t = _mark_conveyor(t)
    return t


def _mark_burst(t: pd.DataFrame) -> pd.DataFrame:
    """Отметить задачи, закрытые в «день зачистки».

    День зачистки — день, в который выполнено любое из двух сочетаний:
    закрыто не меньше BURST_MIN_TASKS задач И не меньше BURST_MIN_SHARE всех
    закрытий сотрудника за период, либо (для небольшого потока) не меньше
    BURST_MIN_TASKS_SOFT задач И не меньше BURST_MIN_SHARE_SOFT закрытий.

    Пара условий обязательна в обоих случаях: 10 задач из 200 — продуктивный
    день, 10 из 25 — разбор хвоста под отчётную дату. Второй путь нужен для
    сотрудника с 14 закрытиями за месяц: порог «10 за день» для него
    недостижим, а 7 задач из 14 в один день — та же зачистка.
    """
    t["close_dt"] = t["fact_close_task_dttm"].dt.normalize()
    closed = t[t["is_closed"] & t["close_dt"].notna()]
    t["burst_close"] = False
    t["closed_same_day_qty"] = 0
    if closed.empty:
        return t

    per_day = (closed.groupby(["emp_id", "close_dt"])["task_code"].size()
               .rename("day_qty").reset_index())
    per_emp = (closed.groupby("emp_id")["task_code"].size()
               .rename("emp_closed").reset_index())
    per_day = per_day.merge(per_emp, on="emp_id", how="left")
    per_day["is_burst"] = (
        ((per_day["day_qty"] >= config.BURST_MIN_TASKS)
         & (per_day["day_qty"] >= config.BURST_MIN_SHARE * per_day["emp_closed"]))
        # второй путь — малый поток: половина месячных закрытий в один день
        | ((per_day["day_qty"] >= config.BURST_MIN_TASKS_SOFT)
           & (per_day["day_qty"] >= config.BURST_MIN_SHARE_SOFT * per_day["emp_closed"])))

    t = t.merge(per_day[["emp_id", "close_dt", "day_qty", "is_burst"]],
                on=["emp_id", "close_dt"], how="left")
    t["closed_same_day_qty"] = num_col(t, "day_qty").astype(int)
    # to_numeric перед fillna: после merge колонка приходит object-типом, и
    # .fillna(False) на нём пишет предупреждение о смене поведения pandas.
    t["burst_close"] = (pd.to_numeric(t["is_burst"], errors="coerce").fillna(0)
                        .astype(bool) & t["is_closed"])
    return t.drop(columns=["day_qty", "is_burst"])


def _mark_conveyor(t: pd.DataFrame) -> pd.DataFrame:
    """Отметить задачи, закрытые подряд с интервалом в минуты.

    Серия — цепочка закрытий одного сотрудника, где соседние отстоят не
    больше чем на CONVEYOR_GAP_MIN минут. Серия длиной от CONVEYOR_MIN_LEN
    задач означает, что задачи закрывались списком: прочитать, позвонить и
    записать результат за это время нельзя.
    """
    t["conveyor_close"] = False
    closed = t[t["is_closed"] & t["fact_close_task_dttm"].notna()].copy()
    if closed.empty:
        return t

    closed = closed.sort_values(["emp_id", "fact_close_task_dttm"])
    gap = closed.groupby("emp_id")["fact_close_task_dttm"].diff()
    new_series = (gap.isna()
                  | (gap > pd.Timedelta(minutes=config.CONVEYOR_GAP_MIN)))
    closed["series_id"] = new_series.cumsum()
    size = closed.groupby("series_id")["task_code"].transform("size")
    flagged = set(closed.loc[size >= config.CONVEYOR_MIN_LEN, "task_code"])
    t["conveyor_close"] = t["task_code"].isin(flagged)
    return t


# --------------------------------------------------------------------------- #
# Шаг 2. Клиенты: комплексная отработка
# --------------------------------------------------------------------------- #
def by_client(t: pd.DataFrame) -> pd.DataFrame:
    """Свод по организации: по одному клиенту задач бывает несколько.

    Оценивать отработку по отдельной задаче недостаточно: клиент, у которого
    закрыли одну задачу из четырёх, формально даёт 25 % закрытия, а по факту
    остаётся неотработанным. Поэтому статус клиента считается по ВСЕМ его
    задачам отчётного месяца.
    """
    if t.empty:
        return pd.DataFrame()

    g = t.groupby("inn")
    c = pd.DataFrame({
        "tasks": g["task_code"].size(),
        "closed": g["is_closed"].sum(),
        "success": g["is_success"].sum(),
        "refused": g["is_refused"].sum(),
        "low_value_success": g["low_value_success"].sum(),
        "no_footprint": g["no_footprint"].sum(),
        "employees": g["emp_id"].nunique(),
        "task_types": g["task_type"].nunique(),
        "plan_qty": g["plan_qty"].sum(),
        "fact_qty": g["fact_qty"].sum(),
        "plan_qty_success": g["plan_qty_success"].sum(),
        "fact_qty_success": g["fact_qty_success"].sum(),
        "potential_qty": g["emp_potential_qty"].max(),
        "close_days": g["close_dt"].nunique(),
        "first_create": g["task_create_dt"].min(),
        "last_close": g["fact_close_task_dttm"].max(),
        "active_tasks": g["has_active"].sum(),
    })
    meta = g.agg(tb_id=("tb_id", "first"), tb_name=("tb_name", "first"),
                 gosb_id=("gosb_id", "first"), gosb_name=("gosb_name", "first"),
                 company_name=("company_name", "first"),
                 segment_name=("segment_name", "first"),
                 emp_fio=("emp_fio", "first"), emp_id=("emp_id", "first"))
    c = meta.join(c).reset_index()

    c["open"] = c["tasks"] - c["closed"]
    c["status"] = np.select(
        [c["closed"] == c["tasks"], c["closed"] > 0],
        ["Отработан полностью", "Отработан частично"],
        default="Не начат")
    c["is_full"] = c["status"] == "Отработан полностью"
    # Противоречие: по одному клиенту одна задача закрыта согласием, другая —
    # «невозможно отработать». В один месяц это взаимоисключающие выводы.
    c["contradiction"] = (c["success"] > 0) & (c["refused"] > 0)
    # Зачистка клиента: две и больше задач, и все они закрыты одним
    # календарным днём. Отдельная задача так закрыться может, весь клиент —
    # нет: разные задачи требуют разных разговоров.
    #
    # Требование «один сотрудник» намеренно НЕ ставится: если по клиенту
    # работают двое и оба закрыли свои задачи в один день, это та же
    # зачистка, а не совпадение.
    c["sweep"] = ((c["tasks"] >= 2) & (c["closed"] == c["tasks"])
                  & (c["close_days"] == 1))
    c["fill_rate"] = _share(c["fact_qty_success"], c["plan_qty_success"])
    # Потенциал известен не по всем клиентам: там, где его нет, доля остаётся
    # пустой, а не нулевой — ноль читался бы как «ничего не взяли».
    pot = pd.to_numeric(c["potential_qty"], errors="coerce")
    c["potential_rate"] = np.where(pot > 0, c["fact_qty"] / pot.where(pot > 0, 1),
                                   np.nan)
    c["no_footprint_all"] = (c["closed"] > 0) & (c["active_tasks"] == 0)
    return c


# --------------------------------------------------------------------------- #
# Шаг 3. Сотрудники
# --------------------------------------------------------------------------- #
def by_employee(t: pd.DataFrame, clients: pd.DataFrame,
                footprint: pd.DataFrame, month_start: date,
                month_end: date) -> pd.DataFrame:
    """Свод по сотруднику: результат, дисциплина, признаки манипуляции."""
    if t.empty:
        return pd.DataFrame()

    g = t.groupby("emp_id")
    e = pd.DataFrame({
        "tasks": g["task_code"].size(),
        "closed": g["is_closed"].sum(),
        "success": g["is_success"].sum(),
        "refused": g["is_refused"].sum(),
        "open": g["is_open"].sum(),
        "stale": g["stale"].sum(),
        "stale_hard": g["stale_hard"].sum(),
        "overdue_closed": g["overdue_closed"].sum(),
        "overdue_open": g["overdue_open"].sum(),
        "no_plan_dt": g["no_plan_dt"].sum(),
        "same_day": g["same_day"].sum(),
        "burst": g["burst_close"].sum(),
        "conveyor": g["conveyor_close"].sum(),
        "no_footprint": g["no_footprint"].sum(),
        "active_after_close": g["active_after_close"].sum(),
        "stub_comment": g["stub_comment"].sum(),
        "no_comment": g["no_comment"].sum(),
        "clone_comment": g["clone_comment"].sum(),
        "quest_filled": g["quest_filled"].sum(),
        "low_value_success": g["low_value_success"].sum(),
        "deals": g["has_deal"].sum(),
        "plan_qty": g["plan_qty"].sum(),
        "fact_qty": g["fact_qty"].sum(),
        "plan_qty_success": g["plan_qty_success"].sum(),
        "fact_qty_success": g["fact_qty_success"].sum(),
        "clients": g["inn"].nunique(),
        "median_cycle": g["cycle_days"].median(),
        "avg_cycle": g["cycle_days"].mean(),
        "p90_cycle": g["cycle_days"].quantile(0.9),
        "avg_overdue_days": g["overdue_days"].mean(),
        "max_closed_day": g["closed_same_day_qty"].max(),
    })
    # Средний возраст открытых задач — отдельной группировкой, а не через
    # g.apply: аргумент include_groups появился только в pandas 2.2, а версия
    # pandas на закрытом контуре заранее неизвестна.
    e = e.join(t.loc[t["is_open"]].groupby("emp_id")["age_days"].mean()
               .rename("avg_age_open"))
    meta = g.agg(emp_fio=("emp_fio", "first"), emp_post=("emp_post", "first"),
                 role_code=("role_code", "first"),
                 manager_fio=("manager_fio", "first"),
                 manager_saphr_id=("manager_saphr_id", "first"),
                 tb_id=("tb_id", "first"), tb_name=("tb_name", "first"),
                 gosb_id=("gosb_id", "first"), gosb_name=("gosb_name", "first"))
    e = meta.join(e).reset_index()

    # --- клиентский разрез ---
    if len(clients):
        cl = clients.groupby("emp_id").agg(
            clients_full=("is_full", "sum"),
            clients_sweep=("sweep", "sum"),
            clients_contradiction=("contradiction", "sum"),
            clients_multi=("tasks", lambda s: int((s >= 2).sum())))
        e = e.merge(cl, left_on="emp_id", right_index=True, how="left")
    for col in ("clients_full", "clients_sweep", "clients_contradiction",
                "clients_multi"):
        e[col] = num_col(e, col).astype(int)

    # --- дни без цифровых следов ---
    e = _silent_days(e, footprint, month_start, month_end)

    # --- доли ---
    e["close_rate"] = _share(e["closed"], e["tasks"])
    e["success_rate"] = _share(e["success"], e["closed"])
    e["success_rate_all"] = _share(e["success"], e["tasks"])
    e["refuse_share"] = _share(e["refused"], e["closed"])
    e["same_day_share"] = _share(e["same_day"], e["closed"])
    e["burst_share"] = _share(e["burst"], e["closed"])
    e["conveyor_share"] = _share(e["conveyor"], e["closed"])
    e["no_footprint_share"] = _share(e["no_footprint"], e["closed"])
    e["stub_share"] = _share(e["stub_comment"], e["closed"])
    e["clone_share"] = _share(e["clone_comment"], e["closed"])
    e["quest_share"] = _share(e["quest_filled"], e["closed"])
    e["low_value_share"] = _share(e["low_value_success"], e["success"])
    e["overdue_share"] = _share(e["overdue_closed"] + e["overdue_open"], e["tasks"])
    e["stale_share"] = _share(e["stale"], e["tasks"])
    e["fill_rate"] = _share(e["fact_qty_success"], e["plan_qty_success"])
    e["client_full_share"] = _share(e["clients_full"], e["clients"])
    e["tasks_per_client"] = _share(e["tasks"], e["clients"])

    e = add_indices(e)
    e = add_triggers(e)
    return e.sort_values(["risk_index", "tasks"], ascending=False)


def _silent_days(e: pd.DataFrame, footprint: pd.DataFrame,
                 month_start: date, month_end: date) -> pd.DataFrame:
    """Рабочие дни месяца, в которые от сотрудника нет ни одного следа.

    След — закрытие задачи, активность (звонок, встреча) или заведение сделки
    по ЛЮБОЙ задаче, включая задачи не целевых типов: день, потраченный на
    отток или сервис, прогулом не является.
    """
    days = work_days(month_start, month_end)
    e["work_days"] = len(days)
    if footprint is None or footprint.empty:
        warn("следов активности за период не найдено — «немые дни» не считаются")
        e["active_days"] = 0
        e["silent_days"] = 0
        e["silent_share"] = 0.0
        return e

    fp = footprint.copy()
    fp["event_dt"] = pd.to_datetime(fp["event_dt"]).dt.date
    fp = fp[fp["event_dt"].isin(set(days))]
    agg = fp.groupby("emp_id")["event_dt"].nunique().rename("active_days")
    e = e.merge(agg, left_on="emp_id", right_index=True, how="left")
    e["active_days"] = num_col(e, "active_days").astype(int)
    e["silent_days"] = (e["work_days"] - e["active_days"]).clip(lower=0)
    e["silent_share"] = _share(e["silent_days"], e["work_days"])
    return e


# --------------------------------------------------------------------------- #
# Шаг 4. Индексы и триггеры
# --------------------------------------------------------------------------- #
def add_indices(e: pd.DataFrame) -> pd.DataFrame:
    """Три интегральных индекса 0-100.

    Индексы линейные: каждый компонент делится на свою управленческую планку
    из config.NORM, обрезается в [0, 1] и умножается на вес. Ни одной
    подобранной константы «чтобы красиво легло» — любое число в дэшборде
    раскладывается обратно на слагаемые.
    """
    n, wr = config.NORM, config.WEIGHTS_RESULT
    e["result_index"] = 100 * (
        wr["success_rate"] * _clip01(e["success_rate"] / n["success_rate"])
        + wr["fill_rate"] * _clip01(e["fill_rate"] / n["fill_rate"])
        + wr["client_full"] * _clip01(e["client_full_share"] / n["client_full"]))

    wd = config.WEIGHTS_DISCIPLINE
    content = 0.6 * (1 - _clip01(e["stub_share"])) + 0.4 * _clip01(e["quest_share"])
    speed = _clip01((2 * n["cycle_days"] - num_col(e, "median_cycle", n["cycle_days"]))
                    / n["cycle_days"])
    e["discipline_index"] = 100 * (
        wd["on_time"] * (1 - _clip01(e["overdue_share"]))
        + wd["presence"] * (1 - _clip01(e["silent_share"]))
        + wd["content"] * content
        + wd["speed"] * speed)

    # Риск-индекс: 100 баллов = все шесть признаков на пороге срабатывания.
    # Это не «вина», а приоритет проверки: индекс показывает, чью отработку
    # смотреть руками в первую очередь.
    tr, wk = config.TRIGGERS, config.WEIGHTS_RISK
    e["risk_index"] = 100 * sum(
        wk[key] * _clip01(e[f"{key}_share"] / tr[key]["share"])
        for key in wk)
    # На малой выборке доли скачут: до порога наблюдений риск не показываем.
    e.loc[e["closed"] < config.MIN_CLOSED_FOR_FLAGS, "risk_index"] *= 0.5
    for col in ("result_index", "discipline_index", "risk_index"):
        e[col] = e[col].round(1)
    return e


def add_triggers(e: pd.DataFrame) -> pd.DataFrame:
    """Бинарные триггеры отклонения — то, что попадает в красный список.

    Триггер ставится только при достаточном числе наблюдений: на пяти
    задачах любая доля равна 0 или 100 % и говорит о размере выборки, а не
    о поведении сотрудника.
    """
    tr = config.TRIGGERS
    enough = e["closed"] >= config.MIN_CLOSED_FOR_FLAGS
    enough_success = e["success"] >= config.MIN_SUCCESS_FOR_FLAGS

    flags = {
        "burst": enough & (e["burst_share"] >= tr["burst"]["share"])
                 & (e["max_closed_day"] >= config.BURST_MIN_TASKS_SOFT),
        "conveyor": enough & (e["conveyor_share"] >= tr["conveyor"]["share"]),
        "low_value": enough_success & (e["low_value_share"] >= tr["low_value"]["share"]),
        "no_footprint": enough & (e["no_footprint_share"] >= tr["no_footprint"]["share"]),
        "clone": enough & (e["clone_share"] >= tr["clone"]["share"]),
        "stub": enough & (e["stub_share"] >= tr["stub"]["share"]),
        "same_day": enough & (e["same_day_share"] >= tr["same_day"]["share"]),
        "silent_days": (e["tasks"] >= config.MIN_TASKS_EMPLOYEE)
                       & (e["silent_share"] >= tr["silent_days"]["share"]),
        "refuse": enough & (e["refuse_share"] >= tr["refuse"]["share"]),
        "sweep": e["clients_sweep"] >= tr["sweep"]["count"],
    }
    for key, series in flags.items():
        e[f"flag_{key}"] = series.fillna(False).astype(bool)
    e["flags_qty"] = sum(e[f"flag_{k}"].astype(int) for k in flags)
    e["flags"] = [
        ",".join(k for k in flags if row[f"flag_{k}"]) for _, row in e.iterrows()]
    return e


# --------------------------------------------------------------------------- #
# Шаг 5. Своды по подразделениям
# --------------------------------------------------------------------------- #
def by_unit(t: pd.DataFrame, e: pd.DataFrame, c: pd.DataFrame,
            keys: list[str]) -> pd.DataFrame:
    """Свод по ТБ или по ГОСБ.

    Доли считаются от СУММ, а не усреднением долей сотрудников: среднее
    долей завышает вклад сотрудника с тремя задачами до веса сотрудника с
    тремястами.
    """
    if t.empty:
        return pd.DataFrame()

    g = t.groupby(keys)
    u = pd.DataFrame({
        "tasks": g["task_code"].size(),
        "closed": g["is_closed"].sum(),
        "success": g["is_success"].sum(),
        "refused": g["is_refused"].sum(),
        "open": g["is_open"].sum(),
        "stale": g["stale"].sum(),
        "overdue_closed": g["overdue_closed"].sum(),
        "overdue_open": g["overdue_open"].sum(),
        "same_day": g["same_day"].sum(),
        "burst": g["burst_close"].sum(),
        "conveyor": g["conveyor_close"].sum(),
        "no_footprint": g["no_footprint"].sum(),
        "stub_comment": g["stub_comment"].sum(),
        "clone_comment": g["clone_comment"].sum(),
        "quest_filled": g["quest_filled"].sum(),
        "low_value_success": g["low_value_success"].sum(),
        "plan_qty": g["plan_qty"].sum(),
        "fact_qty": g["fact_qty"].sum(),
        "plan_qty_success": g["plan_qty_success"].sum(),
        "fact_qty_success": g["fact_qty_success"].sum(),
        "deals": g["has_deal"].sum(),
        "employees": g["emp_id"].nunique(),
        "clients": g["inn"].nunique(),
        "median_cycle": g["cycle_days"].median(),
        "avg_cycle": g["cycle_days"].mean(),
    }).reset_index()

    u["close_rate"] = _share(u["closed"], u["tasks"])
    u["success_rate"] = _share(u["success"], u["closed"])
    u["success_rate_all"] = _share(u["success"], u["tasks"])
    u["refuse_share"] = _share(u["refused"], u["closed"])
    u["same_day_share"] = _share(u["same_day"], u["closed"])
    u["burst_share"] = _share(u["burst"], u["closed"])
    u["conveyor_share"] = _share(u["conveyor"], u["closed"])
    u["no_footprint_share"] = _share(u["no_footprint"], u["closed"])
    u["stub_share"] = _share(u["stub_comment"], u["closed"])
    u["clone_share"] = _share(u["clone_comment"], u["closed"])
    u["quest_share"] = _share(u["quest_filled"], u["closed"])
    u["low_value_share"] = _share(u["low_value_success"], u["success"])
    u["overdue_share"] = _share(u["overdue_closed"] + u["overdue_open"], u["tasks"])
    u["fill_rate"] = _share(u["fact_qty_success"], u["plan_qty_success"])

    # Клиентский разрез подразделения
    if len(c):
        ck = [k for k in keys if k in c.columns]
        cg = c.groupby(ck).agg(clients_total=("inn", "nunique"),
                               clients_full=("is_full", "sum"),
                               clients_multi=("tasks", lambda s: int((s >= 2).sum())),
                               clients_sweep=("sweep", "sum"),
                               clients_contradiction=("contradiction", "sum"))
        u = u.merge(cg.reset_index(), on=ck, how="left")
    for col in ("clients_total", "clients_full", "clients_multi", "clients_sweep",
                "clients_contradiction"):
        u[col] = num_col(u, col).astype(int)
    u["client_full_share"] = _share(u["clients_full"], u["clients_total"])

    # Сотрудники подразделения: сколько под триггерами и каков средний индекс
    if len(e):
        ek = [k for k in keys if k in e.columns]
        eg = e.groupby(ek).agg(
            emp_flagged=("flags_qty", lambda s: int((s > 0).sum())),
            emp_total=("emp_id", "nunique"),
            silent_share=("silent_share", "mean"),
            result_index=("result_index", "mean"),
            discipline_index=("discipline_index", "mean"),
            risk_index=("risk_index", "mean"))
        u = u.merge(eg.reset_index(), on=ek, how="left")
    for col in ("emp_flagged", "emp_total"):
        u[col] = num_col(u, col).astype(int)
    u["emp_flagged_share"] = _share(u["emp_flagged"], u["emp_total"])
    for col in ("result_index", "discipline_index", "risk_index", "silent_share"):
        u[col] = num_col(u, col).round(3)
    return u.sort_values("tasks", ascending=False)


# --------------------------------------------------------------------------- #
# Шаг 6. Итоги и проверка сходимости (правило 25)
# --------------------------------------------------------------------------- #
def totals(t: pd.DataFrame, e: pd.DataFrame, c: pd.DataFrame) -> dict:
    """Числа верхнего уровня — те же, что показывает дэшборд «по системе»."""
    closed = int(t["is_closed"].sum())
    success = int(t["is_success"].sum())
    cycle = t.loc[t["is_closed"], "cycle_days"]
    return {
        "tasks": int(len(t)),
        "employees": int(t["emp_id"].nunique()),
        "clients": int(t["inn"].nunique()),
        "closed": closed,
        "open": int(t["is_open"].sum()),
        "success": success,
        "refused": int(t["is_refused"].sum()),
        "close_rate": closed / len(t) if len(t) else 0.0,
        "success_rate": success / closed if closed else 0.0,
        "median_cycle": float(cycle.median()) if closed else 0.0,
        "avg_cycle": float(cycle.mean()) if closed else 0.0,
        "p90_cycle": float(cycle.quantile(0.9)) if closed else 0.0,
        "same_day_share": float(t.loc[t["is_closed"], "same_day"].mean()) if closed else 0.0,
        "burst_share": float(t.loc[t["is_closed"], "burst_close"].mean()) if closed else 0.0,
        "conveyor_share": float(t.loc[t["is_closed"], "conveyor_close"].mean()) if closed else 0.0,
        "no_footprint_share": float(t.loc[t["is_closed"], "no_footprint"].mean()) if closed else 0.0,
        "stub_share": float(t.loc[t["is_closed"], "stub_comment"].mean()) if closed else 0.0,
        "clone_share": float(t.loc[t["is_closed"], "clone_comment"].mean()) if closed else 0.0,
        "quest_share": float(t.loc[t["is_closed"], "quest_filled"].mean()) if closed else 0.0,
        "low_value_share": float(t.loc[t["is_success"], "low_value_success"].mean()) if success else 0.0,
        "overdue_share": float((t["overdue_closed"] | t["overdue_open"]).mean()),
        "stale_qty": int(t["stale"].sum()),
        "plan_qty": float(t["plan_qty_success"].sum()),
        "fact_qty": float(t["fact_qty_success"].sum()),
        "fill_rate": float(t["fact_qty_success"].sum() / t["plan_qty_success"].sum())
                     if t["plan_qty_success"].sum() else 0.0,
        "clients_multi": int((c["tasks"] >= 2).sum()) if len(c) else 0,
        "clients_full": int(c["is_full"].sum()) if len(c) else 0,
        "clients_sweep": int(c["sweep"].sum()) if len(c) else 0,
        "clients_contradiction": int(c["contradiction"].sum()) if len(c) else 0,
        "emp_flagged": int((e["flags_qty"] > 0).sum()) if len(e) else 0,
        "silent_share": float(e["silent_share"].mean()) if len(e) else 0.0,
        "result_index": float(e["result_index"].mean()) if len(e) else 0.0,
        "discipline_index": float(e["discipline_index"].mean()) if len(e) else 0.0,
        "risk_index": float(e["risk_index"].mean()) if len(e) else 0.0,
    }


def check(t: pd.DataFrame, e: pd.DataFrame, c: pd.DataFrame,
          tb: pd.DataFrame) -> list[str]:
    """Сходимость: суммы частей обязаны совпадать с итогом (правило 25).

    Расхождения не прячутся: они печатаются в прогресс и возвращаются, чтобы
    попасть в дэшборд — отчёт, в котором нельзя проверить число, это
    презентация, а не аналитика.
    """
    issues: list[str] = []

    if len(tb) and int(tb["tasks"].sum()) != len(t):
        issues.append(f"сумма задач по ТБ ({num(tb['tasks'].sum())}) "
                      f"не равна общему числу задач ({num(len(t))})")
    if len(e) and int(e["tasks"].sum()) != len(t):
        issues.append(f"сумма задач по сотрудникам ({num(e['tasks'].sum())}) "
                      f"не равна общему числу задач ({num(len(t))})")
    if len(c) and int(c["tasks"].sum()) != len(t):
        issues.append(f"сумма задач по клиентам ({num(c['tasks'].sum())}) "
                      f"не равна общему числу задач ({num(len(t))})")

    dup = int(t["task_code"].duplicated().sum())
    if dup:
        issues.append(f"дедупликация снимков не сработала: {num(dup)} "
                      f"повторов task_code")

    # Расчётная просрочка против текстового статуса витрины: расхождение не
    # ошибка, но знать его величину надо — статус считает источник, мы считаем
    # по датам, и расходятся они на задачах без плановой даты.
    #
    # Задачи со статусом «невозможно отработать» из сверки исключены: витрина
    # ставит этот статус ВМЕСТО отметки о просрочке, поэтому по датам они
    # просрочены, а по статусу — нет. Это не ошибка расчёта, а приоритет
    # статусов в источнике.
    if "task_text_status" in t:
        by_text = t["task_text_status"].fillna("").str.contains("С просрочкой").sum()
        by_calc = int((t["overdue_closed"] & ~t["is_refused"]).sum())
        if by_text and abs(by_text - by_calc) / max(by_text, 1) > 0.10:
            issues.append(
                f"просрочка по датам ({num(by_calc)}) расходится со статусом "
                f"витрины ({num(by_text)}) больше чем на 10 %")

    bad = int((t["is_success"] & ~t["is_closed"]).sum())
    if bad:
        issues.append(f"{num(bad)} задач помечены успехом, но не закрыты")

    for msg in issues:
        warn(f"сходимость: {msg}")
    if not issues:
        done("сходимость: расхождений нет")
    return issues


def log_totals(tt: dict) -> None:
    """Итоги прогона в консоль — чтобы не открывать файл ради двух чисел."""
    done(f"задач {num(tt['tasks'])} · клиентов {num(tt['clients'])} · "
         f"сотрудников {num(tt['employees'])}")
    done(f"закрыто {tt['close_rate']:.1%} · успех от закрытых {tt['success_rate']:.1%} · "
         f"медиана цикла {tt['median_cycle']:.1f} дн.")
    done(f"в один день с постановкой {tt['same_day_share']:.1%} · "
         f"массовые закрытия {tt['burst_share']:.1%} · "
         f"без следа {tt['no_footprint_share']:.1%}")
    done(f"успехи с нулевым результатом {tt['low_value_share']:.1%} · "
         f"клиентов отработано полностью {num(tt['clients_full'])} из "
         f"{num(tt['clients'])}")
