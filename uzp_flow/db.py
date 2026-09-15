"""Единая точка доступа к БД: engine, чтение, перехват Kerberos, лимит памяти."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config

_KERBEROS_MARKERS = (
    "kerberos", "gssapi", "gss_", "krb5", "ticket expired",
    "credentials cache", "no credentials", "server not found in kerberos database",
)


class KerberosTicketError(RuntimeError):
    pass


def raise_if_kerberos(ex: Exception) -> None:
    """Распознать отказ по Kerberos и остановить работу с инструкцией (правило 10).

    Останавливаемся намеренно: продолжать бессмысленно — ни один следующий запрос
    не пройдёт, а сыпать одинаковыми ошибками в тетрадку только мешает.
    """
    text_ = f"{type(ex).__name__}: {ex}".lower()
    if any(m in text_ for m in _KERBEROS_MARKERS):
        print("=" * 70)
        print("ОСТАНОВЛЕНО: недействительный или отсутствующий Kerberos ticket.")
        print("Обновите Kerberos ticket — выполните `kinit` в консоли,")
        print("затем перезапустите ячейку.")
        print("=" * 70, flush=True)
        raise KerberosTicketError(
            "Обновите Kerberos ticket: выполните kinit в консоли") from ex


@lru_cache(maxsize=8)
def get_engine(url: str) -> Engine:
    """SQLAlchemy engine (кэшируется по URL).

    pool_pre_ping — соединение проверяется перед выдачей: длинная сессия тетрадки
    переживает разрыв на стороне сервера, а не падает на первом же запросе.
    statement_timeout — сервер сам снимет запрос, который висит дольше лимита.
    """
    return create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"options": f"-c statement_timeout={config.SQL_TIMEOUT_MS}"},
    )


def ping(engine: Engine) -> bool:
    """Проверка соединения — первое, что запускается в тетрадке."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as ex:
        raise_if_kerberos(ex)
        raise


def read_sql(engine: Engine, sql: str, params: dict | None = None,
             schema: str | None = None) -> pd.DataFrame:
    """Выполнить SELECT и вернуть DataFrame.

    В SQL используется плейсхолдер {schema} и именованные параметры :name —
    безопасная подстановка значений вместо склейки строк.
    """
    sql = sql.format(schema=schema or config.SCHEMA)
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {})
    except Exception as ex:
        raise_if_kerberos(ex)
        raise


def guard_rows(df: pd.DataFrame, name: str, hint: str = "") -> pd.DataFrame:
    """Не дать выборке съесть память ядра (правило 12).

    Обрезать молча нельзя: тихо усечённая выборка даёт неверные итоги, которые
    выглядят правдоподобно. Поэтому — исключение с указанием, что делать.
    """
    if len(df) > config.MAX_ROWS:
        raise MemoryError(
            f"{name}: {len(df):,} строк — больше лимита {config.MAX_ROWS:,}. "
            + (hint or "Сузьте выборку или агрегируйте на стороне БД.")
        )
    return df


def probe(engine: Engine, base_dt: str, rep_dt: str,
          schema: str | None = None) -> pd.DataFrame:
    """Разведка витрины ДО долгого прогона: есть ли колонки и оба месяца.

    На проме отладиться негде, а самые дорогие отказы — самые глупые: колонка
    называется иначе, месяц ещё не загружен. Дешевле спросить об этом сразу.

    Месяцы считаются ТОЛЬКО по двум запрошенным датам: ведомости на проме
    партиционированы по report_dt, и GROUP BY по всей таблице прочитал бы всю
    историю ради одной справки.
    """
    schema = schema or config.SCHEMA
    cols = read_sql(engine, """
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_schema = :schema
           AND table_name IN ('uzp_data_payroll_m', 'uzp_dim_company',
                              'uzp_data_epk_consolidation', 'uzp_dim_gosb')
    """, {"schema": schema}, schema=schema)

    required = {
        "uzp_data_payroll_m": ["report_dt", "inn", "epk_id", "amt", "enrollment_type",
                               "sys_tb_id", "sys_gosb_id", "company_name",
                               "is_security_force"],
        "uzp_dim_company": ["inn", "company_name", "holding_name"],
        "uzp_data_epk_consolidation": ["inn", "is_military"],
        "uzp_dim_gosb": ["tb_id", "tb_short_name", "new_gosb_id", "new_gosb_name"],
    }
    have = {t: set(g["column_name"]) for t, g in cols.groupby("table_name")}
    missing = {t: sorted(set(c) - have.get(t, set())) for t, c in required.items()}
    missing = {t: c for t, c in missing.items() if c}
    if missing:
        raise RuntimeError(f"В схеме {schema} не хватает колонок: {missing}")

    months = read_sql(engine, """
        SELECT CAST(report_dt AS date) AS report_dt, count(*) AS rows_qty
          FROM {schema}.uzp_data_payroll_m
         WHERE report_dt IN (CAST(:base_dt AS date), CAST(:rep_dt AS date))
         GROUP BY 1 ORDER BY 1
    """, {"base_dt": base_dt, "rep_dt": rep_dt}, schema=schema)

    got = set(str(d) for d in months["report_dt"])
    for d in (base_dt, rep_dt):
        if str(d) not in got:
            raise RuntimeError(
                f"В uzp_data_payroll_m нет строк за {d}. Проверьте дату: "
                f"report_dt — это КОНЕЦ месяца, а не его начало."
            )
    return months
