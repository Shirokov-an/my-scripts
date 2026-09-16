"""Единая точка доступа к БД: engine, чтение, перехват Kerberos, лимит памяти.

Пакет самостоятельный: на закрытый контур едет одной папкой вместе с
тетрадкой, поэтому ничего не импортирует из соседних отчётов.
"""
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

    Останавливаемся намеренно: продолжать бессмысленно — ни один следующий
    запрос не пройдёт, а сыпать одинаковыми ошибками в тетрадку только мешает.
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

    pool_pre_ping — соединение проверяется перед выдачей: длинная сессия
    тетрадки переживает разрыв на стороне сервера, а не падает на первом же
    запросе. statement_timeout — сервер сам снимет висящий запрос.
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
            + (hint or "Сузьте период или агрегируйте на стороне БД.")
        )
    return df
