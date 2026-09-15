"""SQL отчёта о перетоке ФЛ между ИНН. Диалект — Greenplum на ядре PostgreSQL 9.4.

Диалектные ловушки, из-за которых запрос ломается на проме (правило 7):

1. `make_interval(months => n)` в 9.4 не работает — ядро разбирает `=>` как
   оператор. Здесь интервалы не нужны вовсе: оба месяца приходят параметрами.
2. `CAST(inn AS bigint)` по колонке ведомостей роняет ЗАПРОС ЦЕЛИКОМ, а не одну
   строку: `inn` там TEXT, и в нём встречается нечисловое. Поэтому справочники
   приводятся к TEXT, а не ведомости к bigint — приведение bigint→text безопасно
   всегда. Ведущие нули снимаются `ltrim(inn, '0')` с обеих сторон.
3. Фигурные скобки в SQL недопустимы: строка проходит через .format(schema=...),
   и `{1,18}` из регулярного выражения сломало бы подстановку. Длина проверяется
   через char_length, а не квантификатором.
4. `FILTER (WHERE ...)`, оконные функции, FULL JOIN, bool_or, CTE — в 9.4 есть,
   проверено.

Ведомости партиционированы по report_dt: во ВСЕХ обращениях к ним report_dt
стоит в WHERE, иначе читается вся история.
"""
from __future__ import annotations

# Общая часть: портфели получателей обоих месяцев.
#
# Получатель — ЧЕТВЁРКА (ТБ, ГОСБ, ИНН, ЕПК), как задано заказчиком. Порог по
# сумме считается по ПАРЕ (человек, ИНН) за месяц: грейн витрины тоньше метрики
# (строка на каждый вид зачисления), и порог по строке дал бы другое число.
# Человек, получающий от одного ИНН через два подразделения, — два получателя,
# но одна пара.
_BASE_CTE = """
WITH pay AS (
    SELECT CAST(p.report_dt AS date) AS dt,
           p.sys_tb_id               AS tb_id,
           p.sys_gosb_id             AS gosb_id,
           btrim(p.inn)              AS inn,
           p.epk_id                  AS epk_id,
           sum(p.amt)                AS amt,
           max(p.company_name)       AS company_name,
           bool_or(COALESCE(p.is_security_force, false)) AS is_sf
      FROM {schema}.uzp_data_payroll_m p
     WHERE p.report_dt IN (CAST(:base_dt AS date), CAST(:rep_dt AS date))
       AND p.enrollment_type IN (__CODES__)
       AND p.epk_id IS NOT NULL
       AND btrim(COALESCE(p.inn, '')) <> ''
     GROUP BY 1, 2, 3, 4, 5
),
pers_inn AS (
    SELECT dt, epk_id, inn, sum(amt) AS amt
      FROM pay
     GROUP BY dt, epk_id, inn
    HAVING sum(amt) > :amt_min
),
recv AS (
    SELECT y.dt, y.tb_id, y.gosb_id, y.inn, y.epk_id
      FROM pay y
      JOIN pers_inn pn ON pn.dt = y.dt AND pn.epk_id = y.epk_id AND pn.inn = y.inn
),
base AS (SELECT tb_id, gosb_id, inn, epk_id FROM recv WHERE dt = CAST(:base_dt AS date)),
rep  AS (SELECT tb_id, gosb_id, inn, epk_id FROM recv WHERE dt = CAST(:rep_dt  AS date)),
bp   AS (SELECT epk_id, inn, amt FROM pers_inn WHERE dt = CAST(:base_dt AS date)),
rp   AS (SELECT epk_id, inn, amt FROM pers_inn WHERE dt = CAST(:rep_dt  AS date)),

-- Ушедшие и приобретённые ИНН считаются по ЧЕЛОВЕКУ, без подразделения: переезд
-- между ГОСБ одного ИНН перетоком не является, и смешивать их нельзя.
left_p AS (
    SELECT bp.epk_id, bp.inn
      FROM bp LEFT JOIN rp ON rp.epk_id = bp.epk_id AND rp.inn = bp.inn
     WHERE rp.epk_id IS NULL
),
new_p AS (
    SELECT rp.epk_id, rp.inn, rp.amt
      FROM rp LEFT JOIN bp ON bp.epk_id = rp.epk_id AND bp.inn = rp.inn
     WHERE bp.epk_id IS NULL
),
-- ИНН-приёмник человека: НОВЫЙ ИНН с наибольшей суммой зачислений. Если новых
-- ИНН у человека нет, его в этой выборке нет вовсе — значит он не перетёк, а
-- ушёл (в том числе «получал от двух ИНН, стал от одного»).
tgt AS (
    SELECT epk_id, inn AS inn_to
      FROM (SELECT epk_id, inn,
                   row_number() OVER (PARTITION BY epk_id
                                      ORDER BY amt DESC, inn) AS rn
              FROM new_p) t
     WHERE rn = 1
),
flow AS (
    SELECT l.epk_id, l.inn AS inn_from, t.inn_to
      FROM left_p l JOIN tgt t ON t.epk_id = l.epk_id
),
-- Переток приписывается тому подразделению, ГДЕ ЧЕЛОВЕК ЧИСЛИЛСЯ В БАЗОВОМ
-- МЕСЯЦЕ: потерял его именно оно.
flow_src AS (
    SELECT DISTINCT b.tb_id, b.gosb_id, f.inn_from, f.inn_to, f.epk_id
      FROM flow f JOIN base b ON b.epk_id = f.epk_id AND b.inn = f.inn_from
),
edges AS (
    SELECT tb_id, gosb_id, inn_from, inn_to, count(*) AS qty
      FROM flow_src
     GROUP BY tb_id, gosb_id, inn_from, inn_to
),
edge_rank AS (
    SELECT tb_id, gosb_id, inn_from, inn_to, qty,
           row_number() OVER (PARTITION BY tb_id, gosb_id, inn_from
                              ORDER BY qty DESC, inn_to) AS rn,
           sum(qty)    OVER (PARTITION BY tb_id, gosb_id, inn_from) AS flow_out_qty
      FROM edges
)
"""

# --------------------------------------------------------------------------- #
# Итоговая таблица: строка на (ТБ, ГОСБ, ИНН).
SUMMARY = _BASE_CTE + """
, port AS (
    SELECT COALESCE(b.tb_id, r.tb_id)       AS tb_id,
           COALESCE(b.gosb_id, r.gosb_id)   AS gosb_id,
           COALESCE(b.inn, r.inn)           AS inn,
           count(*) FILTER (WHERE b.epk_id IS NOT NULL) AS base_qty,
           count(*) FILTER (WHERE r.epk_id IS NOT NULL) AS rep_qty,
           count(*) FILTER (WHERE r.epk_id IS NULL)     AS out_qty,
           count(*) FILTER (WHERE b.epk_id IS NULL)     AS in_qty
      FROM base b
      FULL JOIN rep r ON r.tb_id = b.tb_id AND r.gosb_id = b.gosb_id
                     AND r.inn = b.inn AND r.epk_id = b.epk_id
     GROUP BY 1, 2, 3
),
-- Переезд между подразделениями ОДНОГО ИНН: в грейне (ТБ, ГОСБ, ИНН) он
-- выглядит уходом, не будучи им. Без этой колонки ротация читается неверно.
gosb_move AS (
    SELECT b.tb_id, b.gosb_id, b.inn, count(DISTINCT b.epk_id) AS gosb_out_qty
      FROM base b
      JOIN rep r2 ON r2.inn = b.inn AND r2.epk_id = b.epk_id
      LEFT JOIN rep r1 ON r1.inn = b.inn AND r1.epk_id = b.epk_id
                      AND r1.gosb_id = b.gosb_id AND r1.tb_id = b.tb_id
     WHERE r1.epk_id IS NULL
     GROUP BY 1, 2, 3
),
pay_attr AS (
    SELECT inn,
           max(CASE WHEN dt = CAST(:rep_dt AS date) THEN company_name END) AS name_rep,
           max(company_name)                  AS name_any,
           bool_or(COALESCE(is_sf, false))    AS is_sf
      FROM pay
     GROUP BY inn
),
-- Справочники приводятся к TEXT (см. ловушку 2 в шапке модуля). Ведущие нули
-- снимаются с обеих сторон: в bigint они не хранятся, а в ведомостях есть.
dict_c AS (
    SELECT CAST(inn AS text)    AS inn_key,
           max(company_name)    AS company_name,
           max(holding_name)    AS holding_name
      FROM {schema}.uzp_dim_company
     WHERE inn IS NOT NULL
     GROUP BY 1
),
dict_m AS (
    SELECT CAST(inn AS text) AS inn_key,
           bool_or(COALESCE(is_military, false)) AS is_military
      FROM {schema}.uzp_data_epk_consolidation
     WHERE inn IS NOT NULL
     GROUP BY 1
),
gosb AS (
    SELECT tb_id, new_gosb_id AS gosb_id,
           max(tb_short_name) AS tb_name,
           max(new_gosb_name) AS gosb_name
      FROM {schema}.uzp_dim_gosb
     GROUP BY 1, 2
)
SELECT p.tb_id,
       g.tb_name,
       p.gosb_id,
       g.gosb_name,
       p.inn,
       COALESCE(dc.company_name, pa.name_rep, pa.name_any) AS company_name,
       dc.holding_name,
       (COALESCE(dm.is_military, false) OR COALESCE(pa.is_sf, false)) AS is_security,
       p.base_qty,
       p.rep_qty,
       p.out_qty,
       p.in_qty,
       COALESCE(gm.gosb_out_qty, 0)   AS gosb_out_qty,
       -- sum() OVER по bigint возвращает numeric, и без приведения численность
       -- приезжает в pandas дробной («80,0» в выгрузке).
       CAST(COALESCE(er.flow_out_qty, 0) AS bigint) AS flow_out_qty,
       er.inn_to,
       COALESCE(dct.company_name, '') AS inn_to_name,
       COALESCE(er.qty, 0)            AS inn_to_qty
  FROM port p
  LEFT JOIN edge_rank er ON er.tb_id = p.tb_id AND er.gosb_id = p.gosb_id
                        AND er.inn_from = p.inn AND er.rn = 1
  LEFT JOIN gosb_move gm ON gm.tb_id = p.tb_id AND gm.gosb_id = p.gosb_id
                        AND gm.inn = p.inn
  LEFT JOIN pay_attr pa  ON pa.inn = p.inn
  LEFT JOIN dict_c  dc   ON dc.inn_key = ltrim(p.inn, '0')
  LEFT JOIN dict_c  dct  ON dct.inn_key = ltrim(er.inn_to, '0')
  LEFT JOIN dict_m  dm   ON dm.inn_key = ltrim(p.inn, '0')
  LEFT JOIN gosb    g    ON g.tb_id = p.tb_id AND g.gosb_id = p.gosb_id
 WHERE p.base_qty >= :min_qty OR p.rep_qty >= :min_qty
"""

# --------------------------------------------------------------------------- #
# Направления перетока: до :top_n приёмников на каждую тройку (ТБ, ГОСБ, ИНН).
# Отдельным запросом, потому что в итоговой таблице приёмник ровно один — самый
# вероятный, — а разбирать спорные случаи нужно по всем направлениям сразу.
EDGES = _BASE_CTE + """
, dict_c AS (
    SELECT CAST(inn AS text) AS inn_key, max(company_name) AS company_name
      FROM {schema}.uzp_dim_company
     WHERE inn IS NOT NULL
     GROUP BY 1
),
src_qty AS (
    SELECT tb_id, gosb_id, inn, count(*) AS base_qty
      FROM base GROUP BY 1, 2, 3
),
pay_name AS (
    SELECT inn, max(company_name) AS company_name FROM pay GROUP BY inn
)
SELECT e.tb_id, e.gosb_id, e.inn_from, e.inn_to, e.qty,
       CAST(e.flow_out_qty AS bigint) AS flow_out_qty, s.base_qty,
       COALESCE(df.company_name, pf.company_name, '')  AS inn_from_name,
       COALESCE(dt2.company_name, pt.company_name, '') AS inn_to_name
  FROM edge_rank e
  JOIN src_qty s ON s.tb_id = e.tb_id AND s.gosb_id = e.gosb_id AND s.inn = e.inn_from
  LEFT JOIN dict_c df  ON df.inn_key = ltrim(e.inn_from, '0')
  LEFT JOIN dict_c dt2 ON dt2.inn_key = ltrim(e.inn_to, '0')
  LEFT JOIN pay_name pf ON pf.inn = e.inn_from
  LEFT JOIN pay_name pt ON pt.inn = e.inn_to
 WHERE e.rn <= :top_n
   AND s.base_qty >= :min_qty
 ORDER BY e.qty DESC
"""


def with_codes(sql: str, codes) -> str:
    """Подставить список кодов зачислений.

    Коды приводятся к int и склеиваются: IN-список переменной длины именованным
    параметром в psycopg2 не передать, а int после приведения инъекцию не несёт.
    """
    ids = ", ".join(str(int(c)) for c in codes)
    if not ids:
        raise ValueError("Список кодов зачислений пуст")
    return sql.replace("__CODES__", ids)
