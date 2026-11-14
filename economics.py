"""Revenue decision support: scenario-weighted contribution and separate original B&A case.

Forecasts are pre-computed ML quantiles. 0.1 and 0.9 tails are held constant
for the 0-0.1 and 0.9-1 portions: a disclosed approximation, not a calibrated
probability distribution. Fixed airline costs are not estimated.
"""
from __future__ import annotations

from functools import lru_cache

QLEVELS = tuple(round(i / 10, 1) for i in range(1, 10))
# Trapezoidal integration of a quantile curve, with flat 10% tails.
PROBABILITY_WEIGHTS = (0.15, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.15)


def _round(value: float) -> float:
    return round(value, 2)


def flight_financials(row: dict, settings: dict, ticket_price: float) -> dict:
    """Financials for any permitted fare; values represent contribution, not net profit."""
    capacity = row['seats']
    b = settings['price_sensitivity']
    base_price = settings['base_price']
    cost = settings['cost_per_passenger']
    scenarios = []
    for q, weight in zip(QLEVELS, PROBABILITY_WEIGHTS):
        demand = max(0.0, row[f'{q:.1f}_base_demand'] - b * (ticket_price - base_price))
        sales = min(capacity, demand)
        scenarios.append({
            'quantile': q, 'weight': weight, 'demand': demand, 'sales': sales,
            'contribution': (ticket_price - cost) * sales,
        })
    expected_sales = sum(x['weight'] * x['sales'] for x in scenarios)
    contribution = sum(x['weight'] * x['contribution'] for x in scenarios)
    downside = scenarios[0]['contribution']
    return {
        'price': ticket_price,
        'expected_sales': expected_sales,
        'expected_revenue': ticket_price * expected_sales,
        'expected_variable_cost': cost * expected_sales,
        'expected_contribution': contribution,
        'low_contribution': downside,
        'median_contribution': scenarios[4]['contribution'],
        'high_contribution': scenarios[8]['contribution'],
        'low_sales': scenarios[0]['sales'],
        'scenarios': scenarios,
    }


def _summary(d: dict) -> dict:
    return {key: _round(d[key]) for key in (
        'price', 'expected_sales', 'expected_revenue', 'expected_variable_cost',
        'expected_contribution', 'low_contribution', 'median_contribution',
        'high_contribution', 'low_sales')}


def _optimal_price(row: dict, settings: dict, objective: str) -> int:
    """Find the exact best *integer-ruble* fare by checking all admissible fares.

    At most ~17k evaluations; finite, deterministic, no optimizers/dependencies.
    """
    lo = int(settings['price_min'])
    hi = int(settings['price_max'])
    best_price = lo
    best_value = float('-inf')
    capacity = row['seats']
    b = settings['price_sensitivity']
    base_price = settings['base_price']
    unit_cost = settings['cost_per_passenger']
    bases = [row[f'{q:.1f}_base_demand'] + b * base_price for q in QLEVELS]
    for price in range(lo, hi + 1):
        margin = price - unit_cost
        sales = [min(capacity, max(0, a - b * price)) for a in bases]
        if objective == 'expected':
            value = margin * sum(w * s for w, s in zip(PROBABILITY_WEIGHTS, sales))
        else:
            value = margin * sales[0]  # conservative: 10th-percentile scenario
        if value > best_value + 1e-9:
            best_value, best_price = value, price
    return best_price


@lru_cache(maxsize=256)
def _cached_optima(route: str, day: str, key: tuple) -> tuple[int, int]:
    # This private helper is called with immutable row/settings representations.
    row_items, setting_items = key
    row, settings = dict(row_items), dict(setting_items)
    return (_optimal_price(row, settings, 'expected'),
            _optimal_price(row, settings, 'conservative'))


def economic_report(route: str, day: str, row: dict, settings: dict, ticket_price: float) -> dict:
    # Cache the substantial price search per route/date rather than per click.
    cache_key = (tuple(sorted(row.items())), tuple(sorted((k, v) for k, v in settings.items() if isinstance(v, (int, float)))))
    expected_fare, conservative_fare = _cached_optima(route, day, cache_key)
    current = flight_financials(row, settings, ticket_price)
    baseline = flight_financials(row, settings, settings['base_price'])
    optimum = flight_financials(row, settings, expected_fare)
    conservative = flight_financials(row, settings, conservative_fare)
    cost = settings['cost_per_passenger']
    pmin, pmax = settings['price_min'], settings['price_max']
    prices = {pmin, pmax, ticket_price, settings['base_price'], expected_fare, conservative_fare}
    prices.update(pmin + i * (pmax - pmin) / 100 for i in range(101))
    curve = []
    for p in sorted(prices):
        r = flight_financials(row, settings, p)
        curve.append({'price': _round(p), 'expected': _round(r['expected_contribution']),
                      'low': _round(r['low_contribution'])})
    quantile_financials = [
        {'quantile': x['quantile'], 'contribution': _round(x['contribution']),
         'sales': _round(x['sales'])} for x in current['scenarios']
    ]
    return {
        'variable_cost_per_passenger': cost,
        'current': _summary(current), 'baseline': _summary(baseline),
        'expected_optimal': _summary(optimum),
        'conservative_optimal': _summary(conservative),
        'uplift_vs_baseline': _round(optimum['expected_contribution'] - baseline['expected_contribution']),
        'uplift_vs_current': _round(optimum['expected_contribution'] - current['expected_contribution']),
        'uplift_pct_vs_baseline': _round(100 * (optimum['expected_contribution'] - baseline['expected_contribution']) /
                                         abs(baseline['expected_contribution'])) if baseline['expected_contribution'] else None,
        'conservative_expected_tradeoff': _round(optimum['expected_contribution'] - conservative['expected_contribution']),
        'conservative_downside_gain': _round(conservative['low_contribution'] - optimum['low_contribution']),
        'curve': curve,
        'quantile_financials': quantile_financials,
        'method': ('Weighted approximation of the quantile function (p10 and p90 held flat in '
                   'unobserved tails); margin = (fare - variable cost per passenger) × sales. '
                   'Full airline profit cannot be estimated without fixed costs.'),
    }


# Separate case: values derived from the ORIGINAL BUSINESS & ANALYTICS conditions.
# Units: demand coefficients in people per thousand RUB; price & cost in kRUB.
CASE_MARKETS = (
    ('Петербург → Москва', 200., 20., 1.),
    ('Москва → Петербург', 160., 20., 1.),
    ('Москва → Сочи', 120., 20., 1.),
    ('Сочи → Москва', 100., 20., 1.),
    ('Петербург → Сочи', 100., 10., 2.),
    ('Сочи → Петербург', 80., 10., 2.),
)
CASE_QUANTITIES = {
    'normal': (90, 70, 50, 40, 40, 30),
    'peak': (130, 70, 50, 40, 20, 30),
    'snow': (80, 60, 40, 30, 35, 25),
}
# Four ordered legs: PM, MS, SM, MP; transit uses two legs.
CASE_LEGS = ((0, 4), (2, 4), (3, 5), (1, 5))


def _case_market_results(quantity: tuple, peak: bool) -> dict:
    markets = []
    total_contribution = 0.0
    for i, (label, normal_a, b, cost) in enumerate(CASE_MARKETS):
        a = 360. if i == 0 and peak else normal_a
        q = quantity[i]
        p = (a - q) / b
        contribution = (p - cost) * q
        total_contribution += contribution
        markets.append({'name': label, 'price': _round(p * 1000), 'tickets': q,
                        'variable_cost': _round(cost * q * 1000),
                        'contribution': _round(contribution * 1000)})
    loads = [sum(quantity[i] for i in idx) for idx in CASE_LEGS]
    return {'markets': markets, 'loads': loads,
            'operating_profit': _round((total_contribution - 400) * 1000),
            'tickets': sum(quantity)}


def network_case(scenario: str) -> dict:
    if scenario not in CASE_QUANTITIES:
        raise ValueError('Unknown mathematical case')
    item = _case_market_results(CASE_QUANTITIES[scenario], scenario == 'peak')
    normal = _case_market_results(CASE_QUANTITIES['normal'], False)
    peak = _case_market_results(CASE_QUANTITIES['peak'], True)
    risk = _case_market_results(CASE_QUANTITIES['snow'], False)
    old_expected = .8 * normal['operating_profit'] - .2 * 4000 * normal['tickets']
    new_expected = .8 * risk['operating_profit'] - .2 * 4000 * risk['tickets']
    item.update({
        'scenario': scenario, 'aircraft_capacity_per_leg': 150,
        'leg_names': ['Петербург → Москва', 'Москва → Сочи', 'Сочи → Москва', 'Москва → Петербург'],
        'normal_profit': normal['operating_profit'], 'peak_profit': peak['operating_profit'],
        'alternative_route_profit': 1290000,
        'alternative_route_delta': _round(1290000 - peak['operating_profit']),
        'shadow_price_one_seat_discrete': 3950,
        'snow_probability': 0.2,
        'snow_expected_old': _round(old_expected),
        'snow_expected_new': _round(new_expected),
        'snow_uplift': _round(new_expected - old_expected),
        'snow_expected_compensation': .2 * 4000 * item['tickets'],
        'snow_expected_profit': _round(new_expected) if scenario == 'snow' else None,
        'source': 'Original business-and-analytics assignment, distinct from the Moscow ML dataset',
    })
    return item