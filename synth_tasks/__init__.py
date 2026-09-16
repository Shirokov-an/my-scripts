"""Сборка синтетической базы для отчёта об отработке задач (открытый контур).

Запуск: `python3 -m synth_tasks`. На закрытом контуре не используется —
там та же схема с теми же именами уже есть на проме.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from uzp_tasks import config
from uzp_tasks.db import get_engine

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def _split_statements(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.endswith(";"):
            out.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    if buf:
        out.append("\n".join(buf))
    return [s for s in out if s.strip()]


def build(conn: str | None = None, schema: str | None = None) -> dict[str, int]:
    from . import generate

    schema = schema or config.SCHEMA
    engine = get_engine(config.db_url(conn))

    generate._backup_old(engine, schema)

    sql = SCHEMA_SQL.read_text(encoding="utf-8").replace("__SCHEMA__", schema)
    with engine.begin() as c:
        for stmt in _split_statements(sql):
            c.execute(text(stmt))

    return generate.generate_all(engine, schema)
