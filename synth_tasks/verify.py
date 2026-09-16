"""Проверка, что аналитика ловит именно тех, кого заложили в синтетику.

Запуск: `python3 -m synth_tasks.verify` (после `python3 -m synth_tasks`).

Смысл проверки. Синтетика знает правду: какой сотрудник — «массовый
закрывальщик», а какой работает добросовестно (раскладка в
output/synth_expect.json). Отчёт правды не знает и обязан прийти к ней сам,
по данным. Скрипт считает, какая доля носителей каждого архетипа поймана
соответствующим триггером, и какая доля добросовестных сотрудников поймана
ошибочно.

Это и есть проверка чисел запуском (правило 20): без неё «триггеры работают»
остаётся утверждением, а не фактом.
"""
from __future__ import annotations

import json
import sys

from uzp_tasks import compute
from uzp_tasks import config as cfg
from uzp_tasks.db import get_engine
from .generate import EXPECT_JSON

# Какой триггер обязан сработать на каком архетипе.
EXPECT_TRIGGER = {
    "mass_closer": ("flag_burst", 0.60),
    "sweeper": ("flag_sweep", 0.50),
    "min_potential": ("flag_low_value", 0.60),
    "instant": ("flag_same_day", 0.50),
    "silent": ("flag_silent_days", 0.50),
    "refuser": ("flag_refuse", 0.60),
    "clone_writer": ("flag_clone", 0.50),
}
# Добросовестных сотрудников под триггерами должно быть немного: полностью
# нулевой ложной тревоги не бывает, но выше этой доли пороги слишком строгие.
FALSE_ALARM_MAX = 0.25


def main(month: str = "2026-08") -> int:
    expect = json.loads(EXPECT_JSON.read_text(encoding="utf-8"))
    engine = get_engine(cfg.db_url())
    res = compute(engine, month)
    emp = res["employees"].set_index("emp_id")

    arch = {}
    for name, ids in expect["archetype_employees"].items():
        for emp_id in ids:
            arch[emp_id] = name

    emp["archetype"] = [arch.get(int(i), "?") for i in emp.index]
    print("\n=== Ловятся ли архетипы ===")
    print(f"  (учитываются сотрудники с {cfg.MIN_CLOSED_FOR_FLAGS}+ закрытыми "
          f"задачами: на меньшем числе триггеры по построению не ставятся —\n"
          f"   доля от двух-трёх задач говорит о размере выборки, а не о поведении)")
    ok = True
    for name, (flag, min_share) in EXPECT_TRIGGER.items():
        sub = emp[(emp["archetype"] == name)
                  & (emp["closed"] >= cfg.MIN_CLOSED_FOR_FLAGS)]
        total = int((emp["archetype"] == name).sum())
        if sub.empty:
            print(f"  {name:14} нет таких сотрудников в выборке месяца")
            continue
        share = float(sub[flag].mean())
        mark = "OK " if share >= min_share else "МАЛО"
        ok &= share >= min_share
        print(f"  {name:14} {flag:18} поймано {share:5.1%} "
              f"(нужно от {min_share:.0%}) · сотрудников {len(sub)} из {total}  {mark}")

    normal = emp[emp["archetype"] == "normal"]
    false_alarm = float((normal["flags_qty"] > 0).mean()) if len(normal) else 0.0
    mark = "OK " if false_alarm <= FALSE_ALARM_MAX else "МНОГО"
    ok &= false_alarm <= FALSE_ALARM_MAX
    print(f"\n  ложная тревога на добросовестных: {false_alarm:5.1%} "
          f"(допустимо до {FALSE_ALARM_MAX:.0%})  {mark}")

    print("\n=== Средний индекс риска по архетипам ===")
    by = (emp.groupby("archetype")
          .agg(сотрудников=("tasks", "size"), задач=("tasks", "mean"),
               риск=("risk_index", "mean"), результат=("result_index", "mean"),
               дисциплина=("discipline_index", "mean"))
          .round(1).sort_values("риск", ascending=False))
    print(by.to_string())

    print("\n=== Числа для methodology_tasks.md ===")
    tt = res["totals"]
    for key in ("tasks", "closed", "success", "close_rate", "success_rate",
                "median_cycle", "avg_cycle", "p90_cycle", "same_day_share",
                "burst_share", "conveyor_share", "no_footprint_share",
                "low_value_share", "stub_share", "clone_share", "quest_share",
                "overdue_share", "fill_rate", "clients", "clients_full",
                "clients_multi", "clients_sweep", "clients_contradiction",
                "emp_flagged", "silent_share"):
        val = tt[key]
        print(f"  {key:22} {val:.4f}" if isinstance(val, float) else
              f"  {key:22} {val}")

    dup = int(res["tasks"]["task_code"].duplicated().sum())
    print(f"\n  дублей task_code после дедупликации снимков: {dup}")
    print("\nИТОГ:", "все проверки пройдены" if ok else "есть непройденные проверки")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-08"))
