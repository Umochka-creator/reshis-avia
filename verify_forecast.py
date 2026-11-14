"""Проверка 155x9 сценариев CSV без дополнительных зависимостей."""
import csv
import math
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

p = Path(__file__).resolve().parent / 'data' / 'my_forecast.csv'
with p.open(encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    expected = {'route', 'date', 'seats'} | {
        f'{i/10:.1f}_{s}' for i in range(1, 10) for s in ('base_demand','price','price_demand')}
    assert expected == set(reader.fieldnames or []), 'Неверная схема CSV'
assert len(rows)==155, f'Неверное число рейсов: {len(rows)}'
assert Counter(x['route'] for x in rows)=={'MOW-AER':31,'MOW-KGD':31,'MOW-LED':31,'MOW-MRV':31,'MOW-OVB':31}
expected_dates=set((date(2026,6,1)+timedelta(days=i)).isoformat() for i in range(31))
assert {x['date'] for x in rows}==expected_dates
assert len({(x['route'],x['date']) for x in rows})==155
for x in rows:
    seats=int(x['seats']);assert seats>0
    ds=[]
    for i in range(1,10):
        q=f'{i/10:.1f}'
        d=float(x[f'{q}_base_demand']);p=float(x[f'{q}_price']);sale=float(x[f'{q}_price_demand'])
        assert all(math.isfinite(v) for v in (d,p,sale))
        assert d>=0 and p>0 and sale>=0
        ds.append(d)
    assert ds==sorted(ds)
print('OK: 155 строк × 9 квантилей, 31 дата, 5 маршрутов. Нет пропусков и пересечений квантилей.')
print('Примечание: валидатор не измеряет MAE и не доказывает точность модели.')

# Дополнительная сверка с точными коэффициентами из routes.csv.
with (Path(__file__).resolve().parent / 'data' / 'routes.csv').open(encoding='utf-8-sig', newline='') as f:
    metadata={r['route']:r for r in csv.DictReader(f)}
assert len(metadata)==5
for row in rows:
    route=metadata[row['route']]
    b=float(route['price_sensitivity']); base_price=float(route['base_price'])
    for i in range(1,10):
        q=f'{i/10:.1f}'
        p=float(row[f'{q}_price']); base=float(row[f'{q}_base_demand'])
        expected=min(float(row['seats']),max(0,base-b*(p-base_price)))
        historical=float(row[f'{q}_price_demand'])
        assert abs(historical-expected)<1.2, (row['route'],row['date'],q,expected,historical)
print('OK: official routes.csv и прогнозы согласованы (расхождение округления < 1,2 пассажира).')
