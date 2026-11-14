from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from main import app, FORECAST, ROUTES, QUANTILES


def test_csv_integrity():
    assert len(FORECAST)==155
    assert len({r for r,d in FORECAST})==5
    assert len({d for r,d in FORECAST})==31
    assert all(row['seats']>0 for row in FORECAST.values())
    assert all([row[f'{q}_base_demand'] for q in QUANTILES] ==
        sorted(row[f'{q}_base_demand'] for q in QUANTILES) for row in FORECAST.values())


def test_auth_and_math():
    with TestClient(app) as client:
        assert client.get('/api/health').json()['records']==155
        assert len(client.get('/api/options').json()['routes'])==5
        payload={"route":"MOW-AER","date":"2026-06-12","price":9000,"quantile":0.5}
        assert client.post('/api/calculate',json=payload).status_code==401
        username='judge_'+uuid.uuid4().hex[:9]
        assert client.post('/api/auth/register',json={'username':username,'password':'test-password-123'}).status_code==201
        assert client.get('/api/auth/me').json()['username']==username
        r=client.post('/api/calculate',json=payload)
        assert r.status_code==200, r.text
        j=r.json(); row=FORECAST[(payload['route'],payload['date'])];p=ROUTES[payload['route']]
        expected=max(0,row['0.5_base_demand']-p['price_sensitivity']*(9000-p['base_price']))
        assert abs(j['median_demand']-expected)<.02
        assert j['median_sales']==min(row['seats'],round(expected,2))
        assert abs(j['median_free'] + j['median_sales']-row['seats'])<.01
        assert len(j['quantiles'])==9
        assert all(j['quantiles'][i]['demand']<=j['quantiles'][i+1]['demand'] for i in range(8))
        assert client.post('/api/calculate',json={**payload,'date':'2026-08-15'}).status_code==404
        assert client.post('/api/calculate',json={**payload,'price':-40}).status_code==422
        assert client.post('/api/auth/logout').status_code==200
        assert client.post('/api/calculate',json=payload).status_code==401


def test_all_official_routes_and_price_limits():
    import csv
    import math
    from pathlib import Path
    official={}
    with (Path(__file__).resolve().parents[1]/'data'/'routes.csv').open(encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            official[row['route']] = row
    assert set(official) == set(ROUTES)
    for route, meta in ROUTES.items():
        for key in ('base_price','price_min','price_max','cost_per_passenger','price_sensitivity'):
            assert math.isclose(float(official[route][key]),float(meta[key]),rel_tol=0,abs_tol=1e-10)
        assert meta['source']=='official'
    with TestClient(app) as client:
        username='verify_'+uuid.uuid4().hex[:9]
        assert client.post('/api/auth/register',json={'username':username,'password':'test-password-123'}).status_code==201
        for route in official:
            settings=ROUTES[route]
            for day in ('2026-06-01','2026-06-12','2026-07-01'):
                for price in (settings['price_min'], settings['base_price'],settings['price_max']):
                    payload={'route':route,'date':day,'price':price,'quantile':0.5}
                    response=client.post('/api/calculate',json=payload)
                    assert response.status_code==200, response.text
                    data=response.json()
                    row=FORECAST[(route,day)]
                    for point in data['quantiles']:
                        q=f"{point['quantile']:.1f}"
                        predicted=max(0,row[f'{q}_base_demand']-settings['price_sensitivity']*(price-settings['base_price']))
                        assert math.isclose(point['demand'],round(predicted,2),abs_tol=0.001)
                        assert math.isclose(point['sales'],round(min(row['seats'],predicted),2),abs_tol=0.001)
                        assert math.isclose(point['unsold_seats'],round(row['seats']-min(row['seats'],predicted),2),abs_tol=0.001)
            for price in (settings['price_min']-1,settings['price_max']+1):
                response=client.post('/api/calculate',json={'route':route,'date':'2026-06-12','price':price})
                assert response.status_code==422
