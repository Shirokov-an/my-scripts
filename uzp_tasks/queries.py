"""SQL отчёта об отработке задач. Диалект — Greenplum на ядре PostgreSQL 9.4.

Диалектные ловушки, из-за которых запрос ломается на проме (правило 7):

1. `make_interval(months => n)` в 9.4 не работает — ядро разбирает `=>` как
   оператор. Здесь интервалы не нужны: границы месяца приходят параметрами.
2. Фигурные скобки в SQL недопустимы: строка проходит через .format(schema=…),
   и любой `{…}` сломал бы подстановку. Поэтому никаких регулярных выражений
   с квантификаторами — длина считается через char_length.
3. `FILTER (WHERE …)`, оконные функции, CTE, `md5()`, `ILIKE` в 9.4 есть,
   проверено.
4. Витрина партиционирована по report_dt: во ВСЕХ обращениях к ней report_dt
   стоит в WHERE, иначе читается вся история (11,9 млн строк).

Про грейн витрины. Одна и та же задача живёт в НЕСКОЛЬКИХ снимках report_dt:
пока она не закрыта, она повторяется из месяца в месяц. Поэтому везде, где
считаются задачи, стоит дедупликация `row_number() OVER (PARTITION BY
task_code ORDER BY report_dt DESC) = 1` — берётся последнее известное
состояние задачи на дату среза. Без неё долгоживущая задача посчиталась бы
столько раз, сколько месяцев она висит, и «дисциплина» тем выше, чем дольше
сотрудник тянет.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Разведка: какие снимки есть в витрине
# --------------------------------------------------------------------------- #
SNAPSHOTS = """
SELECT CAST(report_dt AS date) AS report_dt,
       count(*)                AS rows_qty
  FROM {schema}.uzp_dwh_sale_funnel_task
 WHERE report_dt >= CAST(:dt_from AS date)
 GROUP BY 1
 ORDER BY 1
"""

# Колонки, без которых отчёт не считается. Проверяются ДО долгого прогона:
# на проме отладиться негде, а самый дорогой отказ — самый глупый.
REQUIRED_COLUMNS = {
    "uzp_dwh_sale_funnel_task": [
        "report_dt", "tb_id", "tb_name", "gosb_id", "gosb_name",
        "isu_struct_saphr_id", "emp_fio", "emp_post", "role_code",
        "manager_saphr_id", "manager_fio", "inn", "company_name",
        "segment_name", "task_code", "task_category", "task_type",
        "task_subtype", "src_task_as_code", "task_create_dt",
        "plan_close_task_dttm", "fact_close_task_dttm", "last_active_dttm",
        "last_active_type", "last_active_status", "is_task_closed",
        "is_task_closed_success", "is_task_in_progress", "task_text_status",
        "deal_code", "deal_create_dttm", "plan_staff_deal_qty",
        "fact_staff_deal_qty", "unrealized_deal_potential", "task_comment",
        "task_questionnaire",
    ],
}

PROBE_COLUMNS = """
SELECT table_name, column_name
  FROM information_schema.columns
 WHERE table_schema = :schema
   AND table_name = 'uzp_dwh_sale_funnel_task'
"""

# --------------------------------------------------------------------------- #
# Задачи отчётного месяца: одна строка на задачу, последнее состояние
# --------------------------------------------------------------------------- #
# Длинные тексты (task_text, task_comment, task_questionnaire) наружу НЕ едут
# (правило 3.3): вместо них считаются признаки — длина, отпечаток md5 и факт
# заполнения анкеты. Отпечатка достаточно, чтобы поймать один и тот же
# комментарий на десятках задач, а сам текст для этого не нужен.
TASKS = """
WITH src AS (
    SELECT t.task_code,
           t.report_dt,
           t.tb_id,
           t.tb_name,
           t.gosb_id,
           t.gosb_name,
           t.isu_struct_saphr_id                         AS emp_id,
           t.emp_fio,
           t.emp_post,
           t.role_code,
           t.manager_saphr_id,
           t.manager_fio,
           t.inn,
           t.company_name,
           t.segment_name,
           t.task_category,
           t.task_type,
           t.task_subtype,
           t.src_task_as_code,
           t.campaign_code,
           CAST(t.task_create_dt AS date)                AS task_create_dt,
           t.plan_close_task_dttm,
           t.fact_close_task_dttm,
           t.last_active_dttm,
           t.last_active_type,
           t.last_active_status,
           COALESCE(t.is_task_closed, false)             AS is_closed,
           COALESCE(t.is_task_closed_success, false)     AS is_success,
           COALESCE(t.is_task_in_progress, false)        AS is_in_progress,
           t.task_text_status,
           CASE WHEN t.deal_code IS NOT NULL THEN 1 ELSE 0 END AS has_deal,
           t.deal_create_dttm,
           COALESCE(t.plan_staff_deal_qty, 0)            AS plan_qty,
           COALESCE(t.fact_staff_deal_qty, 0)            AS fact_qty,
           t.unrealized_deal_potential,
           char_length(btrim(COALESCE(t.task_comment, '')))      AS comment_len,
           md5(lower(btrim(COALESCE(t.task_comment, ''))))       AS comment_hash,
           char_length(btrim(COALESCE(t.task_questionnaire, ''))) AS quest_len,
           row_number() OVER (PARTITION BY t.task_code
                              ORDER BY t.report_dt DESC)         AS rn
      FROM {schema}.uzp_dwh_sale_funnel_task t
     WHERE t.report_dt >= CAST(:snap_from AS date)
       AND t.report_dt <= CAST(:as_of AS date)
       AND t.task_create_dt >= CAST(:dt_from AS date)
       AND t.task_create_dt <= CAST(:dt_to AS date)
       AND (t.task_type IN (__TYPES__)
            OR COALESCE(t.task_subtype, '') ILIKE :subtype_like)
)
SELECT task_code, report_dt, tb_id, tb_name, gosb_id, gosb_name,
       emp_id, emp_fio, emp_post, role_code, manager_saphr_id, manager_fio,
       inn, company_name, segment_name, task_category, task_type, task_subtype,
       src_task_as_code, campaign_code, task_create_dt, plan_close_task_dttm,
       fact_close_task_dttm, last_active_dttm, last_active_type,
       last_active_status, is_closed, is_success, is_in_progress,
       task_text_status, has_deal, deal_create_dttm, plan_qty, fact_qty,
       unrealized_deal_potential, comment_len, comment_hash, quest_len
  FROM src
 WHERE rn = 1
"""

# --------------------------------------------------------------------------- #
# Цифровой след сотрудника по дням
# --------------------------------------------------------------------------- #
# Считается по ВСЕМ типам задач, а не только по целевым: день, в который
# сотрудник занимался оттоком или сервисом, не является «немым», и записать
# его в прогул было бы прямой ошибкой.
#
# Что считается следом: закрытие задачи, зафиксированная активность (звонок,
# встреча), заведение сделки. Других систем в витрине нет — ограничение
# описано в methodology_tasks.md.
FOOTPRINT = """
WITH src AS (
    SELECT t.task_code,
           t.isu_struct_saphr_id AS emp_id,
           t.fact_close_task_dttm,
           t.last_active_dttm,
           t.deal_create_dttm,
           row_number() OVER (PARTITION BY t.task_code
                              ORDER BY t.report_dt DESC) AS rn
      FROM {schema}.uzp_dwh_sale_funnel_task t
     WHERE t.report_dt >= CAST(:snap_from AS date)
       AND t.report_dt <= CAST(:as_of AS date)
       AND t.isu_struct_saphr_id IS NOT NULL
),
ev AS (
    SELECT emp_id, CAST(fact_close_task_dttm AS date) AS event_dt, 'close' AS kind
      FROM src WHERE rn = 1 AND fact_close_task_dttm IS NOT NULL
    UNION ALL
    SELECT emp_id, CAST(last_active_dttm AS date), 'active'
      FROM src WHERE rn = 1 AND last_active_dttm IS NOT NULL
    UNION ALL
    SELECT emp_id, CAST(deal_create_dttm AS date), 'deal'
      FROM src WHERE rn = 1 AND deal_create_dttm IS NOT NULL
)
SELECT emp_id,
       event_dt,
       count(*)                                  AS events_qty,
       count(*) FILTER (WHERE kind = 'active')   AS active_qty,
       count(*) FILTER (WHERE kind = 'close')    AS close_qty,
       count(*) FILTER (WHERE kind = 'deal')     AS deal_qty
  FROM ev
 WHERE event_dt >= CAST(:dt_from AS date)
   AND event_dt <= CAST(:dt_to AS date)
 GROUP BY 1, 2
"""

# --------------------------------------------------------------------------- #
# Потенциал численности клиента
# --------------------------------------------------------------------------- #
# Нужен, чтобы отличить «согласие на двух человек в организации на 800» от
# честной отработки мелкого клиента. Снимок берётся последний доступный НЕ
# ПОЗЖЕ даты среза; если витрина потенциала не заполнена, отчёт считается без
# этой метрики — предупреждение печатается в прогресс.
POTENTIAL = """
WITH snap AS (
    SELECT max(report_dt) AS dt
      FROM {schema}.uzp_data_emp_potential
     WHERE report_dt <= CAST(:as_of AS date)
),
tasks AS (
    SELECT DISTINCT t.inn
      FROM {schema}.uzp_dwh_sale_funnel_task t
     WHERE t.report_dt >= CAST(:snap_from AS date)
       AND t.report_dt <= CAST(:as_of AS date)
       AND t.task_create_dt >= CAST(:dt_from AS date)
       AND t.task_create_dt <= CAST(:dt_to AS date)
       AND (t.task_type IN (__TYPES__)
            OR COALESCE(t.task_subtype, '') ILIKE :subtype_like)
)
SELECT p.inn,
       max(p.emp_potential_qty) AS emp_potential_qty
  FROM {schema}.uzp_data_emp_potential p
  JOIN tasks k ON k.inn = p.inn
  CROSS JOIN snap s
 WHERE p.report_dt = s.dt
   AND p.lvl_name = 'gosb'
 GROUP BY 1
"""


def with_types(sql: str, types) -> str:
    """Подставить список типов задач литералами.

    Именованным параметром список не передать одинаково на всех драйверах,
    поэтому литералы — но с проверкой: апостроф в значении означает, что
    список пришёл откуда-то не из конфига, и запрос собирать нельзя.
    """
    vals = []
    for t in types:
        t = str(t)
        if "'" in t or ";" in t:
            raise ValueError(f"Недопустимый тип задачи: {t!r}")
        vals.append(f"'{t}'")
    if not vals:
        raise ValueError("Список типов задач пуст — нечего фильтровать")
    return sql.replace("__TYPES__", ", ".join(vals))
