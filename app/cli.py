"""CLI генератора кампаний Директа.

    python -m app.cli generate https://duplex-shop.ru --brief "рации для охоты"
    python -m app.cli validate --h1 "..." --h2 "..." --text "..."
    python -m app.cli validate-xlsx output/duplex.xlsx
"""

import argparse
import os
import sys

from app.validator import Ad, validate_ad, is_ok


def cmd_validate(args):
    ad = Ad(h1=args.h1 or "", h2=args.h2 or "", text=args.text or "",
            display_url=args.display_url or "")
    issues = validate_ad(ad)
    if not issues:
        print("OK: лимиты соблюдены")
        return 0
    for i in issues:
        print("%s %s: %s" % (i.level, i.field, i.message))
    return 1 if not is_ok(issues) else 0


def cmd_generate(args):
    from app.campaign import generate_campaign
    res = generate_campaign(
        args.url, brief=args.brief or "", region=args.region,
        max_groups=args.max_groups, use_wordstat=not args.no_wordstat,
        combo=not args.no_combo, out_dir=args.outdir, log=print)
    print()
    print("XLSX: %s" % res["xlsx"])
    print("Чеклист: %s" % res["checklist"])
    rep = res["report"]
    print("Валидация: строк %d, ERR %d, WARN %d" %
          (rep["rows"], len(rep["err"]), len(rep["warn"])))
    return 0 if not rep["err"] else 1


def cmd_seo(args):
    from app.seo import run_seo
    res = run_seo(args.url, brief=args.brief or "", region=args.region,
                  max_groups=args.max_groups, use_wordstat=not args.no_wordstat,
                  out_dir=args.outdir, log=print)
    print()
    print("SEO-отчёт: %s" % res["xlsx"])
    print("Групп: %d, фраз: %d, gap-фраз: %d, тем контент-плана: %d" %
          (len(res["core"]), sum(len(g["rows"]) for g in res["core"]),
           len(res["gaps"]), len(res["plan"])))
    if res["forecast_text"]:
        print()
        print(res["forecast_text"])
    return 0


def cmd_forecast(args):
    from app.seo import run_forecast
    params = {"ctr": args.ctr, "cpc": args.cpc, "cr": args.cr}
    res = run_forecast(args.url, brief=args.brief or "", region=args.region,
                       max_groups=args.max_groups, params=params,
                       out_dir=args.outdir, log=print)
    print()
    print(res["text"])
    print("Файл: %s" % res["txt"])
    return 0


def cmd_validate_xlsx(args):
    from app.builder import validate_built_xlsx
    rep = validate_built_xlsx(args.path)
    print("строк данных: %d, объявлений: %d" % (rep["rows"], rep["ads"]))
    for e in rep["err"]:
        print("ERR: %s" % e)
    for w in rep["warn"]:
        print("WARN: %s" % w)
    print("OK" if not rep["err"] else "FAIL: %d ERR" % len(rep["err"]))
    return 0 if not rep["err"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="app.cli",
                                description="Генератор кампаний Яндекс Директа (ТГО, поиск)")
    sub = p.add_subparsers(dest="cmd")

    g = sub.add_parser("generate", help="полный конвейер: URL + бриф -> XLSX")
    g.add_argument("url", help="URL сайта, например https://kuppersberg.ru")
    g.add_argument("--brief", default="", help="что рекламируем (может быть пустым)")
    g.add_argument("--region", default="Москва и область",
                   help='регион показа, имена с листа "Регионы" (по умолчанию Москва и область)')
    g.add_argument("--max-groups", type=int, default=8, help="максимум групп (по умолчанию 8)")
    g.add_argument("--no-wordstat", action="store_true", help="не ходить в Wordstat, шаблонные фразы")
    g.add_argument("--no-combo", action="store_true",
                   help="без комбинаторики: одно объявление на группу, тип Текстово-графическое")
    g.add_argument("--outdir", default="output", help="каталог вывода")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("seo", help="SEO-отчёт: ядро, gap, контент-план, meta + прогноз")
    s.add_argument("url", help="URL сайта")
    s.add_argument("--brief", default="", help="тема/приоритетная категория")
    s.add_argument("--region", default="Москва и область",
                   help='регион для Wordstat (имя; Мск=213, Россия=225)')
    s.add_argument("--max-groups", type=int, default=8)
    s.add_argument("--no-wordstat", action="store_true")
    s.add_argument("--outdir", default="output")
    s.set_defaults(func=cmd_seo)

    f = sub.add_parser("forecast", help="медиапрогноз кампании на данных Wordstat")
    f.add_argument("url", help="URL сайта")
    f.add_argument("--brief", default="")
    f.add_argument("--region", default="Москва и область")
    f.add_argument("--max-groups", type=int, default=8)
    f.add_argument("--ctr", type=float, default=None, help="CTR, доля (например 0.07)")
    f.add_argument("--cpc", type=float, default=None, help="средняя цена клика, руб без НДС")
    f.add_argument("--cr", type=float, default=None, help="конверсия сайта, доля")
    f.add_argument("--outdir", default="output")
    f.set_defaults(func=cmd_forecast)

    v = sub.add_parser("validate", help="проверить объявление по лимитам")
    v.add_argument("--h1", help="заголовок 1 (макс 56)")
    v.add_argument("--h2", help="заголовок 2 (макс 30)")
    v.add_argument("--text", help="текст (макс 81)")
    v.add_argument("--display-url", dest="display_url", help="отображаемая ссылка (макс 20)")
    v.set_defaults(func=cmd_validate)

    vx = sub.add_parser("validate-xlsx", help="проверить готовый файл Коммандера")
    vx.add_argument("path", help="путь до XLSX")
    vx.set_defaults(func=cmd_validate_xlsx)

    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
