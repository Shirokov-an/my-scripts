"""Генератор синтетики для отчёта об отработке задач воронки (открытый контур).

Случайные числа проверяют только то, что код не падает. Чтобы проверить логику,
в синтетике должна встретиться КАЖДАЯ ветка алгоритма (правило 4.3 скилла),
поэтому сотрудники здесь не однородны, а разложены по архетипам поведения:

    normal        — добросовестная отработка: след активности до закрытия,
                    содержательный комментарий, срок 3-15 дней;
    mass_closer   — массовое закрытие: 50-80 % задач в один-два дня, с
                    интервалом в минуты, без активностей;
    min_potential — «конверсия ради конверсии»: успех на клиенте с большим
                    планом при факте 1-2 получателя;
    instant       — закрытие в день создания, часть — в первый час;
    silent        — дни без цифровых следов, задачи висят и просрочиваются;
    refuser       — почти всё закрывает статусом «невозможно отработать»;
    clone_writer  — один и тот же комментарий на десятках задач;
    sweeper       — «зачистка клиента»: все задачи по одному ИНН одним днём.

Раскладка архетипов пишется в output/synth_expect.json — по ней проверяется,
что аналитика ловит именно тех, кого должна (правило 20: числа сверяются
запуском, а не по памяти).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
GOSB_CSV = ROOT / "data" / "s_grnplm_ld_salesntwrk_pcap_sn_uzp.uzp_dim_gosb.csv"
EXPECT_JSON = ROOT / "output" / "synth_expect.json"

SEED = 20260916
RNG = np.random.default_rng(SEED)

# Снимки витрины: строго конец месяца, как на проме.
SNAPSHOTS = [date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31)]
FIRST_CREATE_DT = date(2026, 6, 1)
LAST_CREATE_DT = date(2026, 8, 31)

# ТБ из профиля витрины (ЦА в воронке не встречается).
TB_IDS = (13, 16, 18, 38, 40, 42, 44, 52, 54, 55, 70)

TARGET_TYPES = ("Привлечение ЗП", "Расширение ЗП", "Активация")
OTHER_TYPES = ("Отток", "Контактная политика", "Расчётно-кассовое обслуживание (РКО)",
               "Сервисная задача по договору", "Бизнес-карта")

SUBTYPES = {
    "Привлечение ЗП": ("Привлечение", "Единичные платёжные поручения",
                       "Зарплатный проект конкурента", "Новый клиент"),
    "Расширение ЗП": ("Расширение", "Рост численности", "Неполное покрытие"),
    "Активация": ("Запуск зарплатного проекта", "Запуск после подписания",
                  "Неактивный договор", "Активация выплат"),
    "Отток": ("Фактический отток", "Прогнозный отток"),
    "Контактная политика": ("КП Долго нет активности", "КП Плановая встреча"),
    "Расчётно-кассовое обслуживание (РКО)": ("РКО", ""),
    "Сервисная задача по договору": ("Неактивный договор", ""),
    "Бизнес-карта": ("Бизнес-карта", ""),
}

SEGMENTS = ("Микро", "Малые", "Средние", "Крупные", "Крупнейшие",
            "Рег. госсектор", "SBI")
SEGMENT_W = (0.34, 0.27, 0.17, 0.09, 0.04, 0.06, 0.03)

ROLES = (("МЗП", "Менеджер по продаже зарплатных проектов"),
         ("СЗП", "Специалист по зарплатным проектам"),
         ("МКК", "Менеджер по работе с ключевыми клиентами"),
         ("КМ", "Клиентский менеджер"))
ROLE_W = (0.45, 0.25, 0.15, 0.15)

SRC_AS = ("МЗП", "КМ", "ЦА (УЗП)", "ЦА (SCRM)", "Руководитель", "ПРБР")
SRC_AS_W = (0.34, 0.16, 0.24, 0.12, 0.09, 0.05)

CAMPAIGNS = ("SL0044-05-25-01", "SL0050-09-25-02", "FC0069-04-24-09",
             "EN0006-09-25-01", "SL0013-10-25-01")

ARCHETYPES = ("normal", "mass_closer", "min_potential", "instant",
              "silent", "refuser", "clone_writer", "sweeper")
ARCHETYPE_W = (0.54, 0.08, 0.08, 0.06, 0.08, 0.05, 0.06, 0.05)

SURNAMES = ("Абрамов", "Белов", "Волков", "Гусев", "Дроздов", "Ершов", "Жуков",
            "Зайцев", "Ильин", "Карпов", "Лебедев", "Морозов", "Носов",
            "Орлов", "Панов", "Русаков", "Соколов", "Тихонов", "Уваров",
            "Фомин", "Хохлов", "Цветков", "Чернов", "Шилов", "Щукин",
            "Юдин", "Яковлев", "Бирюков", "Виноградов", "Голубев")
NAMES_M = ("Александр", "Борис", "Виктор", "Геннадий", "Дмитрий", "Егор",
           "Иван", "Кирилл", "Леонид", "Максим", "Николай", "Олег")
NAMES_F = ("Анна", "Валентина", "Галина", "Дарья", "Елена", "Ирина",
           "Ксения", "Людмила", "Марина", "Наталья", "Ольга", "Полина")
PATR_M = ("Александрович", "Борисович", "Викторович", "Дмитриевич",
          "Иванович", "Николаевич", "Олегович", "Сергеевич")
PATR_F = ("Александровна", "Борисовна", "Викторовна", "Дмитриевна",
          "Ивановна", "Николаевна", "Олеговна", "Сергеевна")

COMPANY_KINDS = ("ООО", "АО", "ИП", "МБУ", "ГБУЗ", "ПАО", "НКО")
COMPANY_WORDS = ("Вектор", "Гранит", "Дельта", "Заря", "Импульс", "Каскад",
                 "Лидер", "Магистраль", "Новация", "Орион", "Прогресс",
                 "Ресурс", "Сатурн", "Триумф", "Уют", "Фаворит", "Химпром",
                 "Центр", "Эталон", "Юпитер", "Ярд", "Автодор", "Бриз")

# Содержательные комментарии: разной длины, с деталями — их аналитика должна
# отличать от отписок.
GOOD_COMMENTS = (
    "Встреча с финансовым директором {fio}. Обсудили перевод {n} сотрудников "
    "на зарплатный проект с октября, запрошен реестр. Договорились о повторной "
    "встрече через две недели.",
    "Звонок в бухгалтерию, разговор с главным бухгалтером. Клиент подтвердил "
    "интерес к расширению на {n} человек, просит расчёт по тарифам. Материалы "
    "направлены на почту.",
    "Клиент зачисляет зарплату единичными поручениями на {n} человек. "
    "Показали экономию на комиссии при переходе на реестр, взяли паузу до "
    "закрытия квартала.",
    "Провели презентацию сервиса для отдела кадров. Из {n} получателей "
    "готовы перейти не все, обсуждаем поэтапный перевод. Следующий контакт "
    "после согласования с головной организацией.",
    "Руководитель подтвердил запуск проекта с новой платёжной даты, реестр "
    "на {n} сотрудников передан в операционный отдел. Карты выпускаются.",
    "Отказ клиента: действующий договор с другим банком до конца года, "
    "условия менять не планируют. Повторный контакт согласован на январь.",
)
# Отписки — то, что должно попадать в «формальные закрытия».
STUB_COMMENTS = ("Отработана", "ACCOMPLISHED", "Выполнено", "ок", "Отказ",
                 "Задача отменена в связи с истечением срока отработки",
                 "Сервисное закрытие просроченных предложений", "-")

QUESTIONNAIRES = (
    "1. Зачисление будет?\nДа\n2. Планируемая дата\n{dt}\n3. Количество\n{n}",
    "1. Комментарий\nКлиент подтвердил интерес, ожидаем реестр\n2. fot\n{fot}\n3. amount\n{n}",
    "1. Причина отказа\nДействующий договор с другим банком\n2. Повторный контакт\n{dt}",
)


# --------------------------------------------------------------------------- #
# Справочники
# --------------------------------------------------------------------------- #
def _gosb_frame() -> pd.DataFrame:
    """Реальные пары ТБ/ГОСБ из выгруженного справочника."""
    df = pd.read_csv(GOSB_CSV, encoding="utf-8-sig")
    df = df[["tb_id", "tb_short_name", "tb_full_name", "new_gosb_id",
             "new_gosb_name"]].drop_duplicates(subset=["new_gosb_id"])
    df = df[df["tb_id"].isin(TB_IDS)].reset_index(drop=True)
    df = df.rename(columns={"new_gosb_id": "gosb_id", "new_gosb_name": "gosb_name",
                            "tb_full_name": "tb_name"})
    return df


_CODE_SEQ = {"task": 0, "deal": 0}


def _code(kind: str) -> str:
    """32-символьный код задачи/сделки — как в витрине.

    Детерминированно от счётчика: генератор случайных чисел numpy не умеет
    диапазон 2**128, а уникальность здесь и так обеспечивается счётчиком.
    """
    _CODE_SEQ[kind] += 1
    return hashlib.md5(f"{kind}-{SEED}-{_CODE_SEQ[kind]}".encode()).hexdigest().upper()


def _fio() -> str:
    if RNG.random() < 0.55:
        return (f"{RNG.choice(SURNAMES)}а {RNG.choice(NAMES_F)} "
                f"{RNG.choice(PATR_F)}")
    return f"{RNG.choice(SURNAMES)} {RNG.choice(NAMES_M)} {RNG.choice(PATR_M)}"


def _company_name() -> str:
    return f'{RNG.choice(COMPANY_KINDS)} "{RNG.choice(COMPANY_WORDS)}"'


def _inn(seq: int) -> int:
    """ИНН-подобное 10-значное число. Значения синтетические, не настоящие."""
    return int(7700000000 + seq * 7 + RNG.integers(0, 6))


def _work_dttm(day: date, hour_lo: int = 6, hour_hi: int = 19) -> datetime:
    """Момент внутри рабочего дня."""
    h = int(RNG.integers(hour_lo, hour_hi))
    return datetime.combine(day, time(h, int(RNG.integers(0, 60)),
                                      int(RNG.integers(0, 60))))


def _nearest_active(active_days: dict | None, want: date) -> date | None:
    """Ближайший день, когда сотрудник вообще заходит в систему.

    Нужен «молчуну»: его события стягиваются к нескольким дням месяца,
    остальные рабочие дни остаются без единого следа.
    """
    if not active_days:
        return None
    days = sorted(d for lst in active_days.values() for d in lst)
    for d in days:
        if d >= want:
            return d
    return days[-1] if days else None


def _shift_workday(d: date, days: int) -> date:
    """Сдвиг на N календарных дней с выталкиванием с выходных на понедельник."""
    out = d + timedelta(days=int(days))
    while out.weekday() >= 5:
        out += timedelta(days=1)
    return out


# --------------------------------------------------------------------------- #
# Сотрудники
# --------------------------------------------------------------------------- #
def _employees(gosb: pd.DataFrame) -> pd.DataFrame:
    """По 3-8 исполнителей на ГОСБ плюс руководитель на ГОСБ."""
    rows = []
    saphr = 1_600_000
    for g in gosb.itertuples():
        saphr += 137
        manager_id, manager_fio = saphr, _fio()
        for _ in range(int(RNG.integers(3, 9))):
            saphr += 11
            role_ix = RNG.choice(len(ROLES), p=ROLE_W)
            role_code, post = ROLES[role_ix]
            rows.append({
                "isu_struct_saphr_id": saphr,
                "emp_fio": _fio(),
                "emp_post": post,
                "emp_post_id": 20000000 + int(RNG.integers(100, 9999)),
                "role_code": role_code,
                "manager_saphr_id": manager_id,
                "manager_fio": manager_fio,
                "tb_id": g.tb_id,
                "tb_name": g.tb_name,
                "gosb_id": g.gosb_id,
                "gosb_name": g.gosb_name,
                "archetype": ARCHETYPES[RNG.choice(len(ARCHETYPES), p=ARCHETYPE_W)],
            })
    emp = pd.DataFrame(rows)
    # Гарантия покрытия: в каждом ТБ должен быть хотя бы один носитель каждого
    # архетипа — иначе ветка алгоритма на этом ТБ останется непроверенной.
    for tb in TB_IDS:
        ix = emp.index[emp["tb_id"] == tb].tolist()
        for k, arch in enumerate(ARCHETYPES):
            if not (emp.loc[ix, "archetype"] == arch).any() and k < len(ix):
                emp.loc[ix[k], "archetype"] = arch
    return emp


# --------------------------------------------------------------------------- #
# Клиенты
# --------------------------------------------------------------------------- #
def _clients(emp: pd.DataFrame) -> pd.DataFrame:
    """Клиенты ГОСБ. Часть — с несколькими задачами (комплексная отработка)."""
    rows = []
    seq = 0
    for g, grp in emp.groupby("gosb_id"):
        first = grp.iloc[0]
        # Клиентская база ГОСБ заметно шире месячного потока задач: иначе на
        # каждого клиента приходится по три-четыре задачи от разных
        # сотрудников, и «клиент с несколькими задачами» перестаёт быть
        # исключением — а в витрине это именно исключение.
        for _ in range(int(RNG.integers(120, 260))):
            seq += 1
            seg = SEGMENTS[RNG.choice(len(SEGMENTS), p=SEGMENT_W)]
            # Потенциал численности организации: от сегмента.
            base = {"Микро": 8, "Малые": 30, "Средние": 120, "Крупные": 600,
                    "Крупнейшие": 2500, "Рег. госсектор": 200, "SBI": 60}[seg]
            rows.append({
                "inn": _inn(seq),
                "company_name": _company_name(),
                "segment_name": seg,
                "tb_id": first.tb_id,
                "tb_name": first.tb_name,
                "gosb_id": g,
                "gosb_name": first.gosb_name,
                "emp_potential_qty": int(max(1, RNG.normal(base, base * 0.4))),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Задачи
# --------------------------------------------------------------------------- #
def _plan_qty(potential: int, task_type: str) -> int:
    """План получателей по задаче — доля потенциала организации."""
    share = {"Привлечение ЗП": 0.55, "Расширение ЗП": 0.30,
             "Активация": 0.45}.get(task_type, 0.25)
    return int(max(1, round(potential * share * float(RNG.uniform(0.6, 1.4)))))


def _make_tasks(emp: pd.DataFrame, clients: pd.DataFrame) -> pd.DataFrame:
    """Сгенерировать задачи со всем поведением архетипов."""
    by_gosb = {g: df.reset_index(drop=True) for g, df in clients.groupby("gosb_id")}
    rows: list[dict] = []

    for e in emp.itertuples():
        pool = by_gosb[e.gosb_id]
        arch = e.archetype
        # Нагрузка за три месяца. Взята такой, чтобы месячный поток задач на
        # сотрудника был сопоставим с промышленным (десятки задач): на малом
        # потоке порог массового закрытия недостижим, и ветка алгоритма
        # осталась бы непроверенной.
        n_tasks = int(RNG.integers(45, 130))
        if arch == "silent":
            n_tasks = int(n_tasks * 0.8)

        # Дни массовой зачистки: один-два дня на месяц.
        burst_days = {}
        if arch in ("mass_closer", "sweeper"):
            for snap in SNAPSHOTS:
                d = date(snap.year, snap.month, int(RNG.integers(20, 27)))
                burst_days[(snap.year, snap.month)] = _shift_workday(d, 0)
        burst_seq: dict[date, int] = {}

        # Клон-комментарий на весь месяц.
        clone_text = STUB_COMMENTS[int(RNG.integers(0, len(STUB_COMMENTS)))]

        # «Молчун» появляется в системе редко: все его следы стянуты в 4-7
        # дней месяца, остальные рабочие дни остаются немыми.
        active_days: dict[tuple[int, int], list[date]] = {}
        if arch == "silent":
            for snap in SNAPSHOTS:
                days = sorted({_shift_workday(date(snap.year, snap.month,
                                                   int(RNG.integers(1, 28))), 0)
                               for _ in range(int(RNG.integers(4, 8)))})
                active_days[(snap.year, snap.month)] = days

        # «Зачистщик» работает по пачке клиентов целиком: все задачи такого
        # клиента закрываются одним днём — это и есть проверяемая ветка.
        # Клиентов берём столько, чтобы в КАЖДОМ месяце их набралось больше
        # порога триггера (3 клиента): месяц у клиента один, поэтому пачка
        # делится на три снимка.
        sweep_clients = (pool.sample(n=min(15, len(pool)),
                                     random_state=int(RNG.integers(1, 10**6)))
                         if arch == "sweeper" else None)

        for i in range(n_tasks):
            sweep_task = (arch == "sweeper" and sweep_clients is not None
                          and i < len(sweep_clients) * 3)
            if sweep_task:
                cl = sweep_clients.iloc[i % len(sweep_clients)]
            else:
                cl = pool.iloc[int(RNG.integers(0, len(pool)))]

            if sweep_task:
                # Задачи зачищаемого клиента ставятся в одном месяце, чтобы в
                # отчётный период попадали вместе. Месяц выбирается по
                # КЛИЕНТУ, а не по счётчику задач: иначе три задачи клиента
                # разъедутся по трём месяцам и «зачистки» в выборке не будет.
                snap = SNAPSHOTS[(i % len(sweep_clients)) % len(SNAPSHOTS)]
                create_dt = _shift_workday(
                    date(snap.year, snap.month, int(RNG.integers(1, 18))), 0)
            else:
                create_dt = FIRST_CREATE_DT + timedelta(
                    days=int(RNG.integers(0, (LAST_CREATE_DT - FIRST_CREATE_DT).days + 1)))
                create_dt = _shift_workday(create_dt, 0)
            if create_dt > LAST_CREATE_DT:
                create_dt = LAST_CREATE_DT

            # Задачи зачищаемого клиента всегда целевого типа: иначе их
            # отфильтрует отбор отчёта и ветка снова останется непроверенной.
            is_target = True if sweep_task else RNG.random() < 0.78
            task_type = (TARGET_TYPES[int(RNG.integers(0, len(TARGET_TYPES)))]
                         if is_target
                         else OTHER_TYPES[int(RNG.integers(0, len(OTHER_TYPES)))])
            subs = SUBTYPES[task_type]
            task_subtype = subs[int(RNG.integers(0, len(subs)))] if RNG.random() < 0.6 else None

            potential = int(cl.emp_potential_qty)
            plan_qty = _plan_qty(potential, task_type)
            plan_close = datetime.combine(
                _shift_workday(create_dt, int(RNG.integers(10, 26))),
                time(int(RNG.integers(8, 18)), int(RNG.integers(0, 60))))

            rows.append(_one_task(e, cl, arch, create_dt, plan_close, task_type,
                                  task_subtype, plan_qty, potential,
                                  burst_days, burst_seq, clone_text,
                                  active_days, sweep_task))
    return pd.DataFrame(rows)


def _one_task(e, cl, arch: str, create_dt: date, plan_close: datetime,
              task_type: str, task_subtype, plan_qty: int, potential: int,
              burst_days: dict, burst_seq: dict, clone_text: str,
              active_days: dict | None = None, sweep_task: bool = False) -> dict:
    """Одна задача: исход, даты, след активности, тексты — по архетипу."""
    # --- вероятности исхода ---
    p_closed, p_success, p_refuse = {
        "normal":        (0.86, 0.38, 0.06),
        "mass_closer":   (0.94, 0.30, 0.22),
        "min_potential": (0.90, 0.74, 0.04),
        "instant":       (0.92, 0.33, 0.18),
        "silent":        (0.42, 0.22, 0.10),
        "refuser":       (0.88, 0.07, 0.85),
        "clone_writer":  (0.90, 0.31, 0.14),
        "sweeper":       (0.93, 0.35, 0.17),
    }[arch]

    closed = RNG.random() < p_closed
    # Задачи зачищаемого клиента закрываются все до одной: иначе клиент не
    # попадёт под определение «все задачи закрыты одним днём».
    if sweep_task:
        closed = True
    success = closed and RNG.random() < p_success
    refuse = closed and not success and RNG.random() < p_refuse

    # --- когда закрыли ---
    fact_close = None
    if closed:
        key = (create_dt.year, create_dt.month)
        if sweep_task and key in burst_days:
            day = max(burst_days[key], create_dt)
            seq = burst_seq.get(day, 0)
            burst_seq[day] = seq + 1
            fact_close = datetime.combine(day, time(9, 0)) + timedelta(
                seconds=seq * int(RNG.integers(40, 120)))
        elif arch in ("mass_closer", "sweeper") and key in burst_days and RNG.random() < 0.7:
            day = max(burst_days[key], create_dt)
            seq = burst_seq.get(day, 0)
            burst_seq[day] = seq + 1
            # Пачка: одна задача в 40-120 секунд, с 9 утра.
            fact_close = datetime.combine(day, time(9, 0)) + timedelta(
                seconds=seq * int(RNG.integers(40, 120)))
        elif arch == "instant":
            fact_close = _work_dttm(create_dt) if RNG.random() < 0.75 else \
                datetime.combine(create_dt, time(9, 0)) + timedelta(
                    minutes=int(RNG.integers(3, 55)))
        elif arch == "silent":
            # Молчун закрывает задачи только в те дни, когда вообще заходит
            # в систему: цикл длинный, а след появляется редко.
            want = _shift_workday(create_dt, int(RNG.integers(20, 60)))
            day = _nearest_active(active_days, want)
            fact_close = _work_dttm(day) if day else _work_dttm(want)
        else:
            lag = int(RNG.integers(1, 18)) if RNG.random() < 0.85 else int(RNG.integers(18, 45))
            fact_close = _work_dttm(_shift_workday(create_dt, lag))
        if fact_close.date() > LAST_CREATE_DT:
            # Задача, закрытая за горизонтом витрины, остаётся открытой.
            closed = success = refuse = False
            fact_close = None

    # --- цифровой след ---
    p_active = {"normal": 0.94, "mass_closer": 0.18, "min_potential": 0.72,
                "instant": 0.35, "silent": 0.44, "refuser": 0.55,
                "clone_writer": 0.62, "sweeper": 0.25}[arch]
    last_active_dttm = None
    last_active_type = None
    last_active_status = "Новая"
    if RNG.random() < p_active:
        anchor = fact_close if fact_close else _work_dttm(
            _shift_workday(create_dt, int(RNG.integers(1, 12))))
        delta = timedelta(days=int(RNG.integers(0, 4)), hours=int(RNG.integers(1, 20)))
        act = anchor - delta
        if act < datetime.combine(create_dt, time(7, 0)):
            act = _work_dttm(create_dt)
        if arch == "silent":
            day = _nearest_active(active_days, act.date())
            if day:
                act = _work_dttm(day)
        last_active_dttm = act
        last_active_type = "Встреча" if RNG.random() < 0.38 else "Звонок"
        last_active_status = "Исполнена" if closed else RNG.choice(
            ["В работе", "Запланирована", "Просрочена"], p=[0.5, 0.3, 0.2])
    elif closed:
        last_active_status = "Закрыто"

    # --- результат сделки ---
    deal_code = deal_create = None
    fact_qty = 0
    if success:
        if arch == "min_potential":
            fact_qty = int(RNG.integers(1, 3))            # успех «на бумаге»
        elif arch in ("mass_closer", "sweeper", "instant"):
            fact_qty = int(max(1, RNG.normal(plan_qty * 0.25, plan_qty * 0.2)))
        else:
            fact_qty = int(max(1, RNG.normal(plan_qty * 0.75, plan_qty * 0.3)))
        deal_code = _code("deal")
        deal_create = (fact_close or _work_dttm(create_dt)) - timedelta(
            minutes=int(RNG.integers(5, 600)))
    elif closed and RNG.random() < 0.10:
        # Сделка заведена, но результата нет — такое в витрине встречается.
        deal_code = _code("deal")
        deal_create = (fact_close or _work_dttm(create_dt))

    # --- тексты ---
    comment = None
    if closed:
        if arch == "clone_writer":
            comment = clone_text
        elif arch in ("mass_closer", "sweeper", "instant", "refuser"):
            comment = (STUB_COMMENTS[int(RNG.integers(0, len(STUB_COMMENTS)))]
                       if RNG.random() < 0.82 else _good_comment(fact_qty or plan_qty))
        else:
            comment = (_good_comment(fact_qty or plan_qty) if RNG.random() < 0.78
                       else STUB_COMMENTS[int(RNG.integers(0, len(STUB_COMMENTS)))])
    elif RNG.random() < 0.25:
        comment = _good_comment(plan_qty)

    questionnaire = None
    p_quest = {"normal": 0.42, "min_potential": 0.30, "clone_writer": 0.22,
               "silent": 0.12}.get(arch, 0.08)
    if closed and RNG.random() < p_quest:
        questionnaire = QUESTIONNAIRES[int(RNG.integers(0, len(QUESTIONNAIRES)))].format(
            dt=(create_dt + timedelta(days=20)).strftime("%d.%m.%Y"),
            n=max(1, fact_qty or plan_qty), fot=int(plan_qty * 52000))

    return {
        "tb_id": e.tb_id, "tb_name": e.tb_name,
        "gosb_id": e.gosb_id, "gosb_name": e.gosb_name,
        "saphr_gosb_id": e.gosb_id,
        "manager_saphr_id": e.manager_saphr_id, "manager_fio": e.manager_fio,
        "isu_struct_saphr_id": e.isu_struct_saphr_id,
        "task_struct_saphr_id": None,
        "emp_fio": e.emp_fio, "emp_post_id": e.emp_post_id, "emp_post": e.emp_post,
        "role_code": e.role_code,
        "src_task_as_code": SRC_AS[RNG.choice(len(SRC_AS), p=SRC_AS_W)],
        "src_task_business": "Ключевой клиент" if RNG.random() < 0.004 else None,
        "inn": int(cl.inn), "company_name": cl.company_name,
        "segment_name": cl.segment_name,
        "escalation_parent_task_code": None,
        "task_category": "Задача" if RNG.random() < 0.72 else "Предложение",
        "task_code": _code("task"),
        "task_create_dt": create_dt,
        "plan_close_task_dttm": plan_close if RNG.random() < 0.983 else None,
        "fact_close_task_dttm": fact_close,
        "task_type": task_type, "task_subtype": task_subtype,
        "last_active_type": last_active_type,
        "last_active_dttm": last_active_dttm,
        "last_active_status": last_active_status,
        "campaign_code": (CAMPAIGNS[int(RNG.integers(0, len(CAMPAIGNS)))]
                          if RNG.random() < 0.19 else None),
        "is_task_closed": bool(closed),
        "is_task_closed_success": bool(success),
        "is_task_in_progress": bool(not closed),
        "task_text_status": _text_status(closed, success, refuse, plan_close, fact_close),
        "unrealized_deal_potential": (fact_qty - plan_qty) if deal_code else None,
        "deal_code": deal_code, "deal_create_dttm": deal_create,
        "plan_staff_deal_qty": plan_qty,
        "fact_staff_deal_qty": fact_qty,
        "task_text": _task_text(task_type, potential),
        "task_comment": comment,
        "task_questionnaire": questionnaire,
        "is_escalation_need": (bool(RNG.random() < 0.3) if RNG.random() < 0.0044 else None),
        "archetype": e.archetype,
        "emp_potential_qty": potential,
    }


def _good_comment(n: int) -> str:
    tpl = GOOD_COMMENTS[int(RNG.integers(0, len(GOOD_COMMENTS)))]
    return tpl.format(fio=_fio().split()[1], n=max(1, int(n)))


def _task_text(task_type: str, potential: int) -> str:
    return (f"{task_type}. Потенциал {potential} чел. "
            f"Рекомендуем связаться с клиентом и обсудить условия обслуживания.")


def _text_status(closed: bool, success: bool, refuse: bool,
                 plan_close: datetime | None, fact_close: datetime | None) -> str:
    """Текстовый статус — ровно как в витрине: 5 значений."""
    if not closed:
        if plan_close is not None and plan_close.date() < LAST_CREATE_DT:
            return "Не закрыта: Просрочена"
        return "Не закрыта"
    if refuse:
        return "Закрыта: Статус невозможно отработать"
    if plan_close is not None and fact_close is not None and fact_close > plan_close:
        return "Закрыта: С просрочкой"
    return "Закрыта: Своевременно"


# --------------------------------------------------------------------------- #
# Снимки витрины
# --------------------------------------------------------------------------- #
def _snapshots(tasks: pd.DataFrame) -> pd.DataFrame:
    """Развернуть задачи в помесячные снимки.

    Задача живёт в снимках с месяца создания по месяц закрытия включительно;
    в снимке видно её состояние НА ЭТУ ДАТУ (закрытие, случившееся позже,
    в раннем снимке ещё не отражено). Так на проме и появляются дубли
    task_code между report_dt — отчёт обязан брать последнее состояние.
    """
    frames = []
    for snap in SNAPSHOTS:
        snap_ts = datetime.combine(snap, time(23, 59, 59))
        alive = tasks[tasks["task_create_dt"] <= snap].copy()
        closed_before = alive["fact_close_task_dttm"].notna() & (
            alive["fact_close_task_dttm"] <= snap_ts)
        # закрытые ДО начала месяца снимка из витрины уходят
        month_start = date(snap.year, snap.month, 1)
        gone = alive["fact_close_task_dttm"].notna() & (
            alive["fact_close_task_dttm"] < datetime.combine(month_start, time(0, 0)))
        alive = alive[~gone].copy()
        closed_before = closed_before[~gone]

        not_yet = ~closed_before
        alive.loc[not_yet, "fact_close_task_dttm"] = pd.NaT
        alive.loc[not_yet, "is_task_closed"] = False
        alive.loc[not_yet, "is_task_closed_success"] = False
        alive.loc[not_yet, "is_task_in_progress"] = True
        alive.loc[not_yet, "task_comment"] = None
        alive.loc[not_yet, "task_questionnaire"] = None
        alive.loc[not_yet, "deal_code"] = None
        alive.loc[not_yet, "deal_create_dttm"] = pd.NaT
        alive.loc[not_yet, "fact_staff_deal_qty"] = 0
        alive.loc[not_yet, "unrealized_deal_potential"] = None
        late_active = alive["last_active_dttm"].notna() & (
            alive["last_active_dttm"] > snap_ts)
        alive.loc[late_active, ["last_active_dttm", "last_active_type"]] = [pd.NaT, None]
        # статус пересчитывается на дату снимка
        alive["task_text_status"] = [
            _text_status(bool(c), bool(s),
                         str(st) == "Закрыта: Статус невозможно отработать",
                         p if pd.notna(p) else None, f if pd.notna(f) else None)
            for c, s, st, p, f in zip(alive["is_task_closed"],
                                      alive["is_task_closed_success"],
                                      alive["task_text_status"],
                                      alive["plan_close_task_dttm"],
                                      alive["fact_close_task_dttm"])]
        alive["report_dt"] = snap
        frames.append(alive)
    out = pd.concat(frames, ignore_index=True)
    out["src_update_dttm"] = datetime(2026, 9, 1, 4, 1, 24)
    out["update_dttm"] = datetime(2026, 9, 1, 10, 21, 32)
    return out


# --------------------------------------------------------------------------- #
# Запись
# --------------------------------------------------------------------------- #
TASK_COLUMNS = [
    "report_dt", "tb_id", "tb_name", "gosb_id", "gosb_name", "saphr_gosb_id",
    "manager_saphr_id", "manager_fio", "isu_struct_saphr_id",
    "task_struct_saphr_id", "emp_fio", "emp_post_id", "emp_post", "role_code",
    "src_task_as_code", "src_task_business", "inn", "company_name",
    "segment_name", "escalation_parent_task_code", "task_category", "task_code",
    "task_create_dt", "plan_close_task_dttm", "fact_close_task_dttm",
    "task_type", "task_subtype", "last_active_type", "last_active_dttm",
    "last_active_status", "campaign_code", "is_task_closed",
    "is_task_closed_success", "is_task_in_progress", "task_text_status",
    "unrealized_deal_potential", "deal_code", "deal_create_dttm",
    "plan_staff_deal_qty", "fact_staff_deal_qty", "task_text", "task_comment",
    "task_questionnaire", "is_escalation_need", "src_update_dttm", "update_dttm",
]


def _backup_old(engine: Engine, schema: str) -> None:
    """Сохранить прежнюю таблицу воронки перед первым пересозданием.

    База локальная, но общая для проектов: молча уничтожать чужие данные
    нельзя, поэтому старая таблица уезжает в схему backup_uzp_dash.

    Бэкап делается ОДИН раз. Повторный прогон синтетики ничего не сохраняет:
    иначе второй запуск затёр бы копию прежних данных нашей же синтетикой —
    ровно это здесь однажды и произошло.
    """
    with engine.begin() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :s AND table_name = 'uzp_dwh_sale_funnel_task'"
        ), {"s": schema}).scalar()
        if not exists:
            return
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS backup_uzp_dash"))
        already = conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'backup_uzp_dash' "
            "  AND table_name LIKE 'sale_funnel_task_%'"
        )).scalar()
        if already:
            return
        stamp = datetime.now().strftime("%Y%m%d")
        conn.execute(text(
            f"CREATE TABLE backup_uzp_dash.sale_funnel_task_{stamp} AS "
            f"SELECT * FROM {schema}.uzp_dwh_sale_funnel_task"))


def _copy(engine: Engine, df: pd.DataFrame, schema: str, table: str) -> int:
    """Быстрая загрузка через COPY: to_sql построчно на 70k строк слишком долог."""
    import csv
    import io

    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, sep="\t", na_rep="\\N",
              quoting=csv.QUOTE_NONE, escapechar="\\", date_format="%Y-%m-%d %H:%M:%S")
    buf.seek(0)
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.copy_expert(
            f'COPY {schema}.{table} ({", ".join(df.columns)}) FROM STDIN '
            f"WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\\\N')", buf)
        raw.commit()
    finally:
        raw.close()
    return len(df)


def generate_all(engine: Engine, schema: str) -> dict[str, int]:
    """Собрать и залить синтетику. Возвращает число строк по таблицам."""
    gosb = _gosb_frame()
    emp = _employees(gosb)
    clients = _clients(emp)
    tasks = _make_tasks(emp, clients)
    snaps = _snapshots(tasks)

    # Текст комментария чистим от табуляций/переводов строк только для COPY —
    # в самих данных переводы строк остаются в анкете (как на проме).
    out = snaps[TASK_COLUMNS].copy()
    for col in ("task_text", "task_comment", "task_questionnaire"):
        out[col] = out[col].astype("object").where(out[col].notna(), None)
        out[col] = [None if v is None else str(v).replace("\t", " ").replace("\n", "\\n")
                    for v in out[col]]
    for col in ("is_task_closed", "is_task_closed_success", "is_task_in_progress",
                "is_escalation_need"):
        out[col] = out[col].map({True: "t", False: "f"}).where(out[col].notna(), None)
    # Колонки целых типов: из-за пропусков pandas делает их float, и COPY
    # отвергает «-10.0» для integer. Int64 держит и целое, и пропуск.
    for col in ("tb_id", "gosb_id", "saphr_gosb_id", "manager_saphr_id",
                "isu_struct_saphr_id", "task_struct_saphr_id", "emp_post_id",
                "inn", "unrealized_deal_potential", "plan_staff_deal_qty",
                "fact_staff_deal_qty"):
        out[col] = pd.array(pd.to_numeric(out[col], errors="coerce").round(),
                            dtype="Int64")

    n_tasks = _copy(engine, out, schema, "uzp_dwh_sale_funnel_task")

    pot = clients[["inn", "gosb_id", "emp_potential_qty"]].copy()
    pot["report_dt"] = SNAPSHOTS[-1]
    pot["lvl_name"] = "gosb"
    pot = pot.rename(columns={"gosb_id": "lvl_id"})
    pot = pot[["report_dt", "inn", "lvl_name", "lvl_id", "emp_potential_qty"]]
    n_pot = _copy(engine, pot, schema, "uzp_data_emp_potential")

    _write_expect(emp, tasks)
    return {"uzp_dwh_sale_funnel_task": n_tasks,
            "uzp_data_emp_potential": n_pot,
            "_employees": len(emp), "_clients": len(clients),
            "_tasks_unique": len(tasks)}


def _write_expect(emp: pd.DataFrame, tasks: pd.DataFrame) -> None:
    """Раскладка архетипов — чтобы проверять, кого аналитика обязана поймать."""
    EXPECT_JSON.parent.mkdir(parents=True, exist_ok=True)
    by_arch = emp.groupby("archetype")["isu_struct_saphr_id"].apply(list).to_dict()
    payload = {
        "seed": SEED,
        "snapshots": [str(d) for d in SNAPSHOTS],
        "employees_total": int(len(emp)),
        "tasks_total": int(len(tasks)),
        "archetype_counts": {k: len(v) for k, v in by_arch.items()},
        "archetype_employees": {k: [int(x) for x in v] for k, v in by_arch.items()},
    }
    EXPECT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _unused_hash(s: str) -> str:          # оставлено для отладки текстов
    return hashlib.md5(s.encode("utf-8")).hexdigest()
