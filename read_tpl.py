import openpyxl, collections
p = '/root/projects/hse-education/ai-marketing-direct/templates/example_duplex_tgo.xlsx'
wb = openpyxl.load_workbook(p)
print('вкладки:', wb.sheetnames)
for name in wb.sheetnames:
    ws = wb[name]
    print('\n=====', name, 'строк:', ws.max_row, 'колонок:', ws.max_column)
    hdr = [c.value for c in ws[1]]
    if name.lower().startswith(('текст', 'text')):
        for i, h in enumerate(hdr):
            col = chr(65 + i) if i < 26 else 'A' + chr(65 + i - 26)
            vals = collections.Counter()
            for r in range(2, min(ws.max_row, 3000) + 1):
                v = ws.cell(r, i + 1).value
                if v is not None and str(v).strip():
                    vals[str(v)[:40]] += 1
            filled = sum(vals.values())
            sample = ' | '.join('%s(x%d)' % (k[:28], v) for k, v in vals.most_common(2))
            print('%-3s %-38s заполнено %5d  %s' % (col, str(h)[:38], filled, sample[:90]))
        print('\n--- первые 12 строк (ключевые столбцы):')
        idx = {h: i for i, h in enumerate(hdr)}
        cols = [h for h in hdr if h and any(k in str(h) for k in ('Название группы', 'Фраза', 'Заголовок', 'Текст', 'Ссылка', 'Регион', 'Номер'))][:9]
        print('   ', ' ; '.join(str(c)[:18] for c in cols))
        for r in range(2, 14):
            print('  ', ' ; '.join(str(ws.cell(r, idx[c] + 1).value)[:24] for c in cols))
    else:
        for r in ws.iter_rows(min_row=1, max_row=3, values_only=True):
            print('   ', [str(x)[:20] for x in r[:8]])
