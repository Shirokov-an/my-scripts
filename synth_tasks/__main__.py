"""Точка входа: `python3 -m synth_tasks`."""
from . import build

if __name__ == "__main__":
    counts = build()
    print("Синтетика собрана:")
    for table, n in counts.items():
        print(f"  {table:35} {n:>9,}".replace(",", " "))
