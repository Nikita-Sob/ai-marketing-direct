import openpyxl
p = '/root/projects/hse-education/ai-marketing-direct/templates/example_duplex_tgo.xlsx'
ws = openpyxl.load_workbook(p)['Тексты']
hdr_row = None
for r in range(1, 30):
    if any(ws.cell(r, c).value == 'Тип объявления' for c in range(1, ws.max_column + 1)):
        hdr_row = r; break
print('заголовки в строке:', hdr_row)
hdr = {c: ws.cell(hdr_row, c).value for c in range(1, ws.max_column + 1) if ws.cell(hdr_row, c).value}
print('колонок с заголовками:', len(hdr))
for c, h in hdr.items():
    print('  %-3s %s' % (openpyxl.utils.get_column_letter(c), h))
print('\nслужебные строки до заголовков:')
for r in range(1, hdr_row):
    vals = ['%s=%s' % (openpyxl.utils.get_column_letter(c), str(ws.cell(r, c).value)[:50]) for c in range(1, ws.max_column + 1) if ws.cell(r, c).value is not None]
    if vals: print(' r%d: %s' % (r, ' | '.join(vals)))
# первая группа данных после заголовков
print('\nданные после заголовков:')
for r in range(hdr_row + 1, hdr_row + 12):
    vals = ['%s=%s' % (openpyxl.utils.get_column_letter(c), str(ws.cell(r, c).value)[:36]) for c in range(1, ws.max_column + 1) if ws.cell(r, c).value is not None]
    print(' r%d: %s' % (r, ' | '.join(vals)[:400]))
