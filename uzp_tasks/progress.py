"""Прогресс в консоль (правило 9).

Прогон идёт долго, и молчащая программа неотличима от зависшей. flush=True
обязателен: без него вывод копится в буфере и появляется в тетрадке пачкой
в самом конце, когда он уже не нужен.
"""
from __future__ import annotations

import time

_T0 = time.time()


def _ts() -> str:
    return f"{time.time() - _T0:5.1f}s"


def step(msg: str) -> None:
    print(f"[{_ts()}] → {msg}", flush=True)


def done(msg: str) -> None:
    print(f"[{_ts()}]   ✓ {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[{_ts()}]   ⚠ {msg}", flush=True)


def num(x: float) -> str:
    """Число с неразрывным пробелом-разделителем — для читаемых логов."""
    return f"{int(x):,}".replace(",", " ")
