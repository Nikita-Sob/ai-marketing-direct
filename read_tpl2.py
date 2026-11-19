import openpyxl
p = '/root/projects/hse-education/ai-marketing-direct/templates/example_duplex_tgo.xlsx'
ws = openpyxl.load_workbook(p)['Тексты']
for r in (1, 2, 3, 4):
    vals = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(r, c).value
        if v is not None:
            vals.append('%s=%s' % (openpyxl.utils.get_column_letter(c), str(v)[:34]))
    print('\n-- строка', r, '(%d непустых)' % len(vals))
    print('   ', ' | '.join(vals))
print('\nстрока 5-6 пример:')
for r in (5, 6):
    vals = ['%s=%s' % (openpyxl.utils.get_column_letter(c), str(ws.cell(r, c).value)[:30]) for c in range(1, ws.max_column + 1) if ws.cell(r, c).value is not None]
    print('  ', ' | '.join(vals))
