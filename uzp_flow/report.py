"""Выгрузка результата: две таблицы в CSV.

CSV, а не HTML/Excel: имена организаций выгружаются как есть (правило 14
касается сложных артефактов), а лишняя зависимость на закрытом контуре —
лишний риск установки пакета.

Разделитель «;» и BOM — иначе Excel открывает файл с кириллицей одной колонкой.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config
from .progress import done

# Порядок колонок итоговой таблицы. Ключ — как приходит из SQL, значение —
# шаблон заголовка; {rep} и {base} подставляются месяцами отчёта.
SUMMARY_COLUMNS = [
    ("tb_id",            "ТБ (код)"),
    ("tb_name",          "ТБ"),
    ("gosb_id",          "ГОСБ (код)"),
    ("gosb_name",        "ГОСБ"),
    ("inn",              "ИНН"),
    ("company_name",     "Название"),
    ("holding_name",     "Холдинг"),
    ("is_security",      "Признак силовика"),
    ("rep_qty",          "Численность {rep}"),
    ("base_qty",         "Численность {base}"),
    ("delta_qty",        "Дельта за год"),
    ("out_qty",          "Ушло ФЛ за год"),
    ("in_qty",           "Пришло ФЛ за год"),
    ("out_rate",         "Ротация: ушло, %"),
    ("in_rate",          "Ротация: пришло, %"),
    ("gosb_out_qty",     "Ушло в другой ГОСБ того же ИНН"),
    ("flow_out_qty",     "Перетекло ФЛ в другие ИНН"),
    ("flow_rate",        "Переток, % от портфеля"),
    ("inn_to",           "ИНН перетока"),
    ("inn_to_name",      "Название ИНН перетока"),
    ("inn_to_qty",       "ФЛ, ушедших в этот ИНН"),
    ("flow_kind",        "Тип перетока"),
    ("real_loss_qty",    "Реальная потеря ФЛ за год"),
    ("loss_by_flow_qty", "в т.ч. объяснено перетоком"),
]

EDGE_COLUMNS = [
    ("tb_id",         "ТБ (код)"),
    ("gosb_id",       "ГОСБ (код)"),
    ("inn_from",      "ИНН-источник"),
    ("inn_from_name", "Название источника"),
    ("base_qty",      "Численность источника {base}"),
    ("inn_to",        "ИНН-приёмник"),
    ("inn_to_name",   "Название приёмника"),
    ("qty",           "Перетекло ФЛ"),
    ("flow_out_qty",  "Всего перетекло из источника"),
]


def _rename(df: pd.DataFrame, columns, base_label: str, rep_label: str) -> pd.DataFrame:
    keep = [(src, title.format(base=base_label, rep=rep_label))
            for src, title in columns if src in df.columns]
    return df[[src for src, _ in keep]].rename(columns=dict(keep))


def write(summary: pd.DataFrame, edges: pd.DataFrame,
          base_label: str, rep_label: str,
          out_dir: Path | None = None) -> dict[str, Path]:
    """Записать итоговую таблицу и направления перетока. Возвращает пути."""
    out_dir = Path(out_dir or config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = summary.copy()
    summary["is_security"] = summary["is_security"].map({True: "Да", False: "Нет"})

    s = _rename(summary, SUMMARY_COLUMNS, base_label, rep_label)
    e = _rename(edges, EDGE_COLUMNS, base_label, rep_label)

    paths = {
        "summary": out_dir / f"flow_summary_{rep_label}_vs_{base_label}.csv",
        "edges": out_dir / f"flow_edges_{rep_label}_vs_{base_label}.csv",
    }
    for key, frame in (("summary", s), ("edges", e)):
        frame.to_csv(paths[key], index=False, sep=";", encoding="utf-8-sig",
                     decimal=",")
        done(f"{key}: {len(frame):,} строк -> {paths[key]}".replace(",", " "))
    return paths
