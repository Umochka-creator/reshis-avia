import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from main import app, FORECAST, ROUTES
from economics import network_case, PROBABILITY_WEIGHTS


def test_weights_and_network_case_match_original_mathematics():
    assert math.isclose(sum(PROBABILITY_WEIGHTS), 1.0)
    normal = network_case('normal')
    peak = network_case('peak')
    snow = network_case('snow')
    assert normal['operating_profit'] == 705000
    assert peak['operating_profit'] == 1625000
    assert peak['loads'] == [150, 70, 70, 100]
    assert peak['alternative_route_delta'] == -335000
    assert peak['shadow_price_one_seat_discrete'] == 3950
    assert snow['snow_expected_old'] == 308000
    assert snow['snow_expected_new'] == 328000
    assert snow['snow_uplift'] == 20000
    assert snow['snow_expected_compensation'] == 216000


def test_guest_economics_for_all_routes_and_risk():
    with TestClient(app) as client:
        for route, settings in ROUTES.items():
            for date in ('2026-06-01', '2026-06-12', '2026-07-01'):
                r = client.post('/api/calculate', json={
                    'route': route, 'date': date, 'price': settings['base_price'],
                    'quantile': 0.5,
                })
                assert r.status_code == 200, (route, date, r.text)
                x = r.json()
                e = x['economics']
                assert e['current']['price'] == settings['base_price']
                assert e['expected_optimal']['expected_contribution'] >= e['baseline']['expected_contribution'] - .01
                assert e['conservative_optimal']['low_contribution'] >= e['expected_optimal']['low_contribution'] - .01
                assert settings['price_min'] <= e['expected_optimal']['price'] <= settings['price_max']
                assert settings['price_min'] <= e['conservative_optimal']['price'] <= settings['price_max']
                assert math.isclose(e['current']['expected_revenue'] - e['current']['expected_variable_cost'],
                                    e['current']['expected_contribution'], abs_tol=.05)
                assert len(e['quantile_financials']) == 9
                assert len(e['curve']) >= 101
                assert e['uplift_vs_baseline'] >= -.01
                row = FORECAST[(route, date)]
                expected_sales = sum(w * min(row['seats'], row[f'{i/10:.1f}_base_demand'])
                                     for i, w in enumerate(PROBABILITY_WEIGHTS, start=1))
                assert math.isclose(e['current']['expected_sales'], expected_sales, abs_tol=.02)


def test_network_endpoint_and_source_separation():
    with TestClient(app) as client:
        assert client.get('/api/network-case?scenario=peak').json()['peak_profit'] == 1625000
        assert client.get('/api/network-case?scenario=snow').json()['snow_uplift'] == 20000
        assert client.get('/api/network-case?scenario=bogus').status_code == 422
        assert client.get('/api/auth/me').status_code == 401
        assert client.get('/api/network-case?scenario=normal').status_code == 200


def test_finance_ui_integrity():
    folder = Path(__file__).resolve().parents[1] / 'static'
    html = (folder/'index.html').read_text()
    js = (folder/'app.js').read_text()
    required_ids = ['profitChart', 'upliftValue', 'financialRevenue', 'financialMargin',
                    'financialOptimal', 'riskExpectedPrice', 'riskSafePrice',
                    'networkProfit', 'networkRows', 'networkLegs', 'networkNormal',
                    'applyExpectedPrice', 'applySafePrice']
    for name in required_ids:
        assert f'id="{name}"' in html, name
    assert 'renderEconomics(result.economics)' in js
    assert "loadNetworkCase('peak')" in js
    assert 'отдельный ML' not in js  # no conflation in raw JS