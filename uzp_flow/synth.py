"""Синтетика открытого контура для отчёта о перетоке.

Схема и имена таблиц повторяют пром точь-в-точь — DDL берётся из того же
`synth/schema.sql`, что и у остальных отчётов проекта. Тогда SQL переносится
внутрь без единой правки, и в коде нет ветвлений «если пром».

Данные здесь НЕ случайные. Каждый сценарий ниже — отдельная ветка разбора, и
ожидаемый ответ по нему записан рядом числом. Ветка, которой нет в синтетике,
уедет на пром непроверенной, и первым, кто её отладит, будет пром. Проверяет
ожидания `selfcheck()`.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config
from .progress import done, step, warn

SCHEMA_SQL = config.ROOT / "synth" / "schema.sql"
TABLES = ("uzp_data_payroll_m", "uzp_dim_company",
          "uzp_data_epk_consolidation", "uzp_dim_gosb")

BASE_DT = "2025-08-31"
REP_DT = "2026-08-31"
NOISE_DT = "2026-02-28"       # месяц вне отчёта: если он попал в итог — сломан WHERE

AMT_OK = 50_000               # выше порога 2500
AMT_LOW = 1_000               # ниже порога: деньги идут, получателя в метрике нет
CODE_SALARY = 1               # «Заработная плата» — в списке зарплатных
CODE_ADVANCE = 16             # «Аванс по заработной плате» — тоже в списке
CODE_OTHER = 7                # «Прочие выплаты» — ВНЕ списка


class _Rows:
    """Накопитель строк ведомостей.

    Один получатель месяца даёт НЕСКОЛЬКО строк — по строке на вид зачисления.
    Разбор обязан суммировать их, а не считать строки, поэтому сумма всегда
    раскладывается на две части.
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def recv(self, dt: str, tb: int, gosb: int, inn: str, epk: int,
             amt: float = AMT_OK, code: int = CODE_SALARY,
             is_sf: bool | None = None, name: str | None = None) -> None:
        parts = ((code, 0.6), (CODE_ADVANCE if code == CODE_SALARY else code, 0.4))
        for part_code, share in parts:
            self.rows.append({
                "acc_num": f"40817810{gosb % 10000:04d}{epk % 100000000:08d}",
                "amt": round(amt * share, 2),
                "company_name": name or f"ОРГ {inn}",
                "enrollment_type": part_code,
                "enrollment_transcription": "Заработная плата",
                "epk_id": epk,
                "gosb_id": gosb + 900000,      # старый номер: со справочником НЕ сходится
                "sys_gosb_id": gosb,
                "inn": inn,
                "tb_id": None,                 # на проме пуста — заполнен sys_tb_id
                "sys_tb_id": tb,
                "report_dt": dt,
                "transaction_qty": 1,
                "is_security_force": is_sf,
                "modified_dttm": dt,
            })

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def _gosb_pair() -> tuple[int, int, int]:
    """ТБ и два его ГОСБ из справочника: нужны для переезда внутри одного ИНН."""
    g = pd.read_csv(config.CSV_GOSB)[["tb_id", "new_gosb_id"]].drop_duplicates()
    for tb, grp in g.groupby("tb_id"):
        ids = sorted(int(x) for x in grp["new_gosb_id"])
        if len(ids) >= 2:
            return int(tb), ids[0], ids[1]
    raise RuntimeError("В справочнике ГОСБ нет ТБ с двумя подразделениями")


def build_payroll() -> tuple[pd.DataFrame, dict]:
    """Ведомости трёх месяцев и ожидаемые ответы по каждому сценарию."""
    tb, gosb_a, gosb_b = _gosb_pair()
    r = _Rows()
    epk = 1_126_000_000_000_000_000
    expect: dict[str, dict] = {}

    def people(n: int) -> list[int]:
        nonlocal epk
        out = list(range(epk, epk + n))
        epk += n
        return out

    def month(dt: str, inn: str, ids, gosb: int = gosb_a, **kw) -> None:
        for e in ids:
            r.recv(dt, tb, gosb, inn, e, **kw)

    # --- 1. Массовый переход: 80 из 100 человек уехали в новый ИНН ----------
    p = people(100)
    month(BASE_DT, "7700000001", p)
    month(REP_DT, "7700000002", p[:80])
    month(REP_DT, "7700000001", p[80:85])
    # p[85:] не получают нигде — это уход, а не переток
    expect["7700000001"] = dict(base_qty=100, rep_qty=5, out_qty=95, in_qty=0,
                                flow_out_qty=80, inn_to="7700000002",
                                inn_to_qty=80, flow_kind="массовый переход",
                                real_loss_qty=95, gosb_out_qty=0)
    expect["7700000002"] = dict(base_qty=0, rep_qty=80, out_qty=0, in_qty=80,
                                flow_out_qty=0, flow_kind="", real_loss_qty=0)

    # --- 2. Ротация: трое ушли в действующий ИНН, четверо пришли ------------
    p = people(60)
    q = people(20)          # свой портфель ИНН-приёмника
    newcomers = people(4)
    month(BASE_DT, "7700000003", p)
    month(BASE_DT, "7700000004", q)
    month(REP_DT, "7700000003", p[5:] + newcomers)     # p[0:3] ушли, p[3:5] исчезли
    month(REP_DT, "7700000004", q + p[:3])
    expect["7700000003"] = dict(base_qty=60, rep_qty=59, out_qty=5, in_qty=4,
                                flow_out_qty=3, inn_to="7700000004", inn_to_qty=3,
                                flow_kind="ротация", real_loss_qty=1)
    expect["7700000004"] = dict(base_qty=20, rep_qty=23, out_qty=0, in_qty=3,
                                flow_out_qty=0, flow_kind="", real_loss_qty=0)

    # --- 3. Обрыв: организация потеряла всех, люди не всплыли нигде ---------
    p = people(40)
    month(BASE_DT, "7700000005", p)
    expect["7700000005"] = dict(base_qty=40, rep_qty=0, out_qty=40, in_qty=0,
                                flow_out_qty=0, flow_kind="", real_loss_qty=40,
                                is_security=True)

    # --- 4. Совместители: получал от двух ИНН, стал от одного ---------------
    # Это НЕ переток: нового ИНН у человека не появилось.
    p = people(20)
    month(BASE_DT, "7700000006", p)
    month(BASE_DT, "7700000007", p)
    month(REP_DT, "7700000006", p[12:])
    month(REP_DT, "7700000007", p)
    expect["7700000006"] = dict(base_qty=20, rep_qty=8, out_qty=12, in_qty=0,
                                flow_out_qty=0, flow_kind="", real_loss_qty=12)
    expect["7700000007"] = dict(base_qty=20, rep_qty=20, out_qty=0, in_qty=0,
                                flow_out_qty=0, flow_kind="", real_loss_qty=0)

    # --- 5. Второй ИНН В ДОБАВОК к первому: источник не потерял никого ------
    p = people(30)
    month(BASE_DT, "7700000008", p)
    month(REP_DT, "7700000008", p)
    month(REP_DT, "7700000009", p[:10])
    expect["7700000008"] = dict(base_qty=30, rep_qty=30, out_qty=0, in_qty=0,
                                flow_out_qty=0, flow_kind="", real_loss_qty=0)
    expect["7700000009"] = dict(base_qty=0, rep_qty=10, out_qty=0, in_qty=10,
                                flow_out_qty=0, flow_kind="", real_loss_qty=0)

    # --- 6. Переезд между ГОСБ ОДНОГО ИНН: ушёл из подразделения, не из ИНН -
    p = people(25)
    month(BASE_DT, "7700000010", p, gosb=gosb_a)
    month(REP_DT, "7700000010", p[:10], gosb=gosb_a)
    month(REP_DT, "7700000010", p[10:], gosb=gosb_b)
    expect["7700000010"] = dict(base_qty=25, rep_qty=10, out_qty=15, in_qty=0,
                                flow_out_qty=0, gosb_out_qty=15, flow_kind="",
                                real_loss_qty=15, gosb_id=gosb_a)

    # --- 7. Ведущий ноль в ИНН + сползание ниже порога ---------------------
    p = people(25)
    month(BASE_DT, "0770000123", p)
    month(REP_DT, "0770000123", p[8:])
    month(REP_DT, "0770000123", p[:8], amt=AMT_LOW)
    expect["0770000123"] = dict(base_qty=25, rep_qty=17, out_qty=8, in_qty=0,
                                flow_out_qty=0, flow_kind="", real_loss_qty=8,
                                company_name="Организация 770000123")

    # --- 8. Два новых ИНН у одного человека: приёмник — где сумма больше ----
    p = people(10)
    month(BASE_DT, "7700000011", p)
    month(REP_DT, "7700000011", p[6:])
    month(REP_DT, "7700000012", p[:6], amt=3_000)
    month(REP_DT, "7700000013", p[:6], amt=60_000)
    expect["7700000011"] = dict(base_qty=10, rep_qty=4, out_qty=6, in_qty=0,
                                flow_out_qty=6, inn_to="7700000013", inn_to_qty=6,
                                flow_kind="ротация", real_loss_qty=6)

    # --- 9. Нечисловой ИНН: в справочниках его нет, имя берётся из ведомости
    p = people(12)
    month(BASE_DT, "ИНН777", p)
    month(REP_DT, "ИНН777", p[5:])
    month(REP_DT, "7700000014", p[:5])
    expect["ИНН777"] = dict(base_qty=12, rep_qty=7, out_qty=5, in_qty=0,
                            flow_out_qty=5, inn_to="7700000014", inn_to_qty=5,
                            flow_kind="ротация", real_loss_qty=5,
                            company_name="ОРГ ИНН777")

    # --- 10. Сирота: ИНН вне справочников, силовик известен только из ведомости
    p = people(20)
    month(BASE_DT, "7700000900", p, is_sf=True)
    month(REP_DT, "7700000900", p, is_sf=True)
    expect["7700000900"] = dict(base_qty=20, rep_qty=20, out_qty=0, in_qty=0,
                                flow_out_qty=0, is_security=True, holding_name=None)

    # --- 11. Мелочь: ниже порога материальности, в отчёт не попадает --------
    p = people(3)
    month(BASE_DT, "7700000015", p)
    month(REP_DT, "7700000015", p)
    expect["7700000015"] = dict(absent=True)

    # --- 12. Смена кода выплаты: деньги те же, зарплатного кода больше нет --
    p = people(20)
    month(BASE_DT, "7700000016", p)
    month(REP_DT, "7700000016", p[10:])
    month(REP_DT, "7700000016", p[:10], code=CODE_OTHER)
    expect["7700000016"] = dict(base_qty=20, rep_qty=10, out_qty=10, in_qty=0,
                                flow_out_qty=0, flow_kind="", real_loss_qty=10)

    # --- 13. Шум соседнего месяца: в отчёт не должен попасть вовсе ----------
    month(NOISE_DT, "7700009999", people(50))
    expect["7700009999"] = dict(absent=True)

    return r.frame(), {"tb_id": tb, "gosb_a": gosb_a, "gosb_b": gosb_b,
                       "base_dt": BASE_DT, "rep_dt": REP_DT, "orgs": expect}


def build_dicts(payroll: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Справочники ЮЛ. Часть ИНН в них отсутствует — как на проме."""
    orphans = {"7700000900", "ИНН777", "7700009999"}
    numeric = sorted({i for i in payroll["inn"].unique()
                      if i not in orphans and i.isdigit()})

    company, epk = [], []
    for n, inn in enumerate(numeric):
        inn_bi = int(inn)                    # ведущий ноль здесь теряется — как в bigint
        company.append({
            "epk_id": 900_000_000 + n,
            "company_name": f"Организация {inn_bi}",
            "inn": inn_bi,
            # холдинг заполнен не у всех: на проме поле пустое примерно у трети
            "holding_name": "Холдинг силовых ведомств" if n % 3 == 0 else None,
            "segment_name": "Рег. госсектор",
            "modified_dttm": REP_DT,
        })
        # У одного ИНН может быть НЕСКОЛЬКО ЕПК, и признак силовика стоит не на
        # всех: поэтому он собирается через bool_or, а не берётся из одной строки.
        epk.append({"epk_id": 900_000_000 + n, "inn": inn_bi,
                    "company_name": f"Организация {inn_bi}",
                    "is_military": False, "status_name": "Активна",
                    "modified_dttm": REP_DT})
        if inn == "7700000005":
            epk.append({"epk_id": 950_000_000 + n, "inn": inn_bi,
                        "company_name": f"Организация {inn_bi}",
                        "is_military": True, "status_name": "Активна",
                        "modified_dttm": REP_DT})
    return pd.DataFrame(company), pd.DataFrame(epk)


def _statements(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.endswith(";"):
            out.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    return [s for s in out if s.strip()]


def apply_schema(engine: Engine, schema: str) -> None:
    """Создать схему и только те таблицы, которые читает отчёт.

    DDL берётся из общего schema.sql проекта: держать вторую копию определения
    пром-таблицы означало бы однажды разойтись с ней и не заметить.
    """
    sql = SCHEMA_SQL.read_text(encoding="utf-8").replace("__SCHEMA__", schema)
    stmts = [s for s in _statements(sql)
             if s.lstrip().upper().startswith("CREATE SCHEMA")
             or any(t in s for t in TABLES)]
    stmts = [s for s in stmts if "__SCHEMA_T__" not in s]
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))
        for stmt in stmts:
            conn.execute(text(stmt))


def _bulk(engine: Engine, df: pd.DataFrame, table: str, schema: str) -> int:
    df = df.where(pd.notnull(df), None)
    df.to_sql(table, engine, schema=schema, if_exists="append", index=False,
              method="multi", chunksize=500)
    return len(df)


def build(conn: str | None = None, schema: str | None = None) -> dict:
    """Пересоздать схему и наполнить её синтетикой. Возвращает ожидания."""
    from .db import get_engine

    schema = schema or config.SCHEMA
    engine = get_engine(config.db_url(conn))

    step("схема открытого контура")
    apply_schema(engine, schema)

    payroll, expect = build_payroll()
    company, epk = build_dicts(payroll)
    gosb = pd.read_csv(config.CSV_GOSB)

    counts = {
        "uzp_dim_gosb": _bulk(engine, gosb, "uzp_dim_gosb", schema),
        "uzp_dim_company": _bulk(engine, company, "uzp_dim_company", schema),
        "uzp_data_epk_consolidation": _bulk(engine, epk,
                                            "uzp_data_epk_consolidation", schema),
        "uzp_data_payroll_m": _bulk(engine, payroll, "uzp_data_payroll_m", schema),
    }
    for table, n in counts.items():
        done(f"{table:30s} {n:>7} строк")
    return expect


def selfcheck(summary: pd.DataFrame, expect: dict) -> int:
    """Сверить отчёт с ожиданиями синтетики. Возвращает число расхождений.

    Проверка именно числами: «отработало без ошибок» ничего не значит, если
    ветка посчитала не то. Держать эти числа в голове нельзя, а сверять глазами —
    то же самое, что не сверять.
    """
    step("сверка с ожиданиями синтетики")
    d = summary.set_index("inn", drop=False)
    bad = 0
    for inn, want in expect["orgs"].items():
        got = d[d["inn"] == inn]
        if want.get("absent"):
            if not got.empty:
                warn(f"{inn}: не должен попасть в отчёт, а попал")
                bad += 1
            continue
        if got.empty:
            warn(f"{inn}: строки нет в отчёте")
            bad += 1
            continue
        if "gosb_id" in want:
            got = got[got["gosb_id"] == want["gosb_id"]]
        row = got.iloc[0]
        for key, value in want.items():
            if key in ("absent", "gosb_id"):
                continue
            actual = row[key]
            if value is None:
                ok = pd.isna(actual)
            elif isinstance(value, bool):
                ok = bool(actual) == value
            elif isinstance(value, str):
                ok = str(actual) == value
            else:
                ok = pd.notna(actual) and float(actual) == float(value)
            if not ok:
                warn(f"{inn}.{key}: ожидалось {value!r}, получено {actual!r}")
                bad += 1
    if bad:
        warn(f"расхождений с синтетикой: {bad}")
    else:
        done(f"все {len(expect['orgs'])} сценариев синтетики сошлись")
    return bad


def main() -> None:
    """Собрать синтетику, прогнать отчёт целиком и сверить его с ожиданиями."""
    from . import run

    expect = build()
    result = run(base_dt=expect["base_dt"], rep_dt=expect["rep_dt"])
    raise SystemExit(1 if selfcheck(result["summary"], expect) else 0)


if __name__ == "__main__":
    main()
