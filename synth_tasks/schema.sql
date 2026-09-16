-- Схема открытого контура для отчёта об отработке задач воронки.
--
-- ВАЖНО: имена схемы, таблиц и колонок повторяют промышленные ТОЧЬ-В-ТОЧЬ
-- (правило 4.2 скилла) — тогда SQL из uzp_tasks/queries.py переносится на пром
-- без единой правки и в коде нет ветвлений «если пром».
--
-- Типы взяты из профиля витрины:
--   data/profiles/…uzp_dwh_sale_funnel_task.profile.json (46 колонок)
--   data/profiles/…uzp_data_emp_potential.profile.json

CREATE SCHEMA IF NOT EXISTS __SCHEMA__;

-- Старую таблицу воронки (усечённая, от прежнего отчёта uzp_dash) сохраняем
-- в схему backup_uzp_dash, а не теряем: локальная база общая для проектов.
CREATE SCHEMA IF NOT EXISTS backup_uzp_dash;

DROP TABLE IF EXISTS __SCHEMA__.uzp_dwh_sale_funnel_task;

CREATE TABLE __SCHEMA__.uzp_dwh_sale_funnel_task (
  report_dt                   date         NOT NULL,   -- снимок на КОНЕЦ месяца
  tb_id                       integer,
  tb_name                     varchar,
  gosb_id                     integer,
  gosb_name                   varchar,
  saphr_gosb_id               integer,
  manager_saphr_id            bigint,                  -- руководитель сотрудника
  manager_fio                 varchar,
  isu_struct_saphr_id         bigint,                  -- ТАБЕЛЬНЫЙ исполнителя
  task_struct_saphr_id        bigint,                  -- в витрине пуст на 100%
  emp_fio                     varchar,
  emp_post_id                 bigint,
  emp_post                    varchar,
  role_code                   varchar,                 -- МЗП / СЗП / МКК / КМ …
  src_task_as_code            varchar,                 -- система-источник задачи
  src_task_business           varchar,
  inn                         bigint,
  company_name                varchar,
  segment_name                varchar,
  escalation_parent_task_code varchar,
  task_category               varchar,                 -- Задача / Предложение
  task_code                   varchar,                 -- ключ задачи
  task_create_dt              date,
  plan_close_task_dttm        timestamp,               -- плановый срок
  fact_close_task_dttm        timestamp,               -- фактическое закрытие
  task_type                   varchar,
  task_subtype                varchar,
  last_active_type            varchar,                 -- Звонок / Встреча
  last_active_dttm            timestamp,               -- последний цифровой след
  last_active_status          varchar,
  campaign_code               varchar,
  is_task_closed              boolean,
  is_task_closed_success      boolean,
  is_task_in_progress         boolean,
  task_text_status            varchar,
  unrealized_deal_potential   integer,
  deal_code                   varchar,
  deal_create_dttm            timestamp,
  plan_staff_deal_qty         integer,                 -- план получателей
  fact_staff_deal_qty         integer,                 -- факт получателей
  task_text                   varchar,
  task_comment                varchar,                 -- отчёт об отработке
  task_questionnaire          varchar,                 -- анкета/чек-лист
  is_escalation_need          boolean,
  src_update_dttm             timestamp,
  update_dttm                 timestamp
);

-- Индексы под запросы отчёта. На Greenplum распределение другое, но на
-- локальной базе без них выборка за месяц идёт полным сканом.
CREATE INDEX ix_sft_report_dt ON __SCHEMA__.uzp_dwh_sale_funnel_task (report_dt);
CREATE INDEX ix_sft_create_dt ON __SCHEMA__.uzp_dwh_sale_funnel_task (task_create_dt);

-- Потенциал численности организации: (inn, lvl_id) на снимок.
-- lvl_name: 'gosb' | 'tb' | 'sb'; для отчёта берётся уровень 'gosb'.
DROP TABLE IF EXISTS __SCHEMA__.uzp_data_emp_potential;

CREATE TABLE __SCHEMA__.uzp_data_emp_potential (
  report_dt        date,
  inn              bigint,
  lvl_name         text,
  lvl_id           integer,
  emp_potential_qty integer
);

CREATE INDEX ix_emp_pot_inn ON __SCHEMA__.uzp_data_emp_potential (inn, lvl_id);
