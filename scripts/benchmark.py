# -*- coding: utf-8 -*-
"""Воспроизводимый бенчмарк: реальные сайты, автопроверки качества файла.

Запуск:  .venv/bin/python scripts/benchmark.py
Результат: output/benchmark.json + таблица в stdout.
Прогоны идут в отдельный каталог output/bench и в runs.jsonl НЕ пишутся
(чтобы не смешивать с тестовыми).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import openpyxl  # noqa: E402

from app import campaign as camp  # noqa: E402
from app import metrics  # noqa: E402
from app.validator import commander_len  # noqa: E402

SITES = [
    ("Kuppersberg", "https://kuppersberg.ru", "встраиваемая техника"),
    ("Duplex Shop", "https://duplex-shop.ru", "рации для охоты"),
    ("Vodovoz", "https://vodovoz.ru", "доставка воды"),
    ("Строймаркет", "https://stroymarket.moscow/", "строительные материалы"),
    ("СИЗ-ГО", "https://sizgo.ru/", "средства защиты"),
]
MOJIBAKE = re.compile(r"[ÐÑ][\x80-\xbf]|Ð|Ã.|â€|\ufffd|[РС][\u0080-\u00bf]")
COL = dict(A=1, J=10, K=11, L=12, P=16, V=22, W=23, Y=25, BF=58)


def check_file(path: str) -> dict:
    ws = openpyxl.load_workbook(path)["Тексты"]
    r = 16
    plus = minus = 0
    texts, moji, combo_full, link_ok, bs_max = set(), 0, 0, 0, 0
    last_main = None
    while ws.cell(r, 1).value in ("-", "+"):
        kind = ws.cell(r, 1).value
        cells = [ws.cell(r, c).value for c in range(1, 70)]
        s = " ".join(str(c) for c in cells if c)
        if MOJIBAKE.search(s):
            moji += 1
        if kind == "-":
            minus += 1
            last_main = (ws.cell(r, 10).value, ws.cell(r, 11).value, ws.cell(r, 12).value)
            if ws.cell(r, 12).value:
                texts.add(ws.cell(r, 12).value)
        else:
            plus += 1
            heads = [ws.cell(r, c).value for c in range(16, 23)]
            txts = [ws.cell(r, c).value for c in range(23, 26)]
            if all(heads) and all(txts):
                combo_full += 1
            if last_main == (ws.cell(r, 10).value, ws.cell(r, 11).value, ws.cell(r, 12).value):
                link_ok += 1
        bf = ws.cell(r, COL["BF"]).value
        if bf:
            for d in str(bf).split("||"):
                bs_max = max(bs_max, commander_len(d.strip("[] ")))
        r += 1
    return {"rows_minus": minus, "rows_plus": plus, "mojibake_rows": moji,
            "unique_main_texts": len(texts), "combo_full": combo_full,
            "combo_linked": link_ok, "bs_desc_max": bs_max}


def main():
    # изолируем лог бенчмарка от боевого runs.jsonl
    metrics.RUNS_LOG = ROOT / "output" / "bench" / "runs_bench.jsonl"
    res = []
    for name, url, brief in SITES:
        t0 = time.time()
        row: dict = {"site": name, "url": url}
        try:
            out = camp.generate_campaign(url, brief, out_dir="output/bench",
                                         log=lambda *_: None)
            st = out["stats"]
            row.update(ok=True, seconds=round(time.time() - t0, 1),
                       groups=st["groups"], phrases=st["phrases"],
                       err=len(out["report"]["err"]), warn=len(out["report"]["warn"]),
                       **check_file(out["xlsx"]))
        except Exception as e:  # noqa: BLE001
            row.update(ok=False, seconds=round(time.time() - t0, 1), error=str(e)[:200])
        res.append(row)
        print(json.dumps(row, ensure_ascii=False))
    Path("output/benchmark.json").write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                             encoding="utf-8")


if __name__ == "__main__":
    main()
