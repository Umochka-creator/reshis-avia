from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from main import app


def test_guest_can_forecast_and_auth_is_optional():
    with TestClient(app) as client:
        assert client.get('/api/auth/me').status_code == 401
        base_prices = {
            'MOW-AER': 9000,
            'MOW-KGD': 7500,
            'MOW-LED': 5500,
            'MOW-MRV': 8000,
            'MOW-OVB': 12000,
        }
        for route, price in base_prices.items():
            response = client.post('/api/calculate', json={
                'route': route, 'date': '2026-06-12',
                'price': price, 'quantile': 0.5,
            })
            assert response.status_code == 200, (route, response.text)
            assert len(response.json()['quantiles']) == 9

        assert client.post('/api/calculate', json={
            'route': 'MOW-AER', 'date': '2026-06-12',
            'price': 1,
        }).status_code == 422
