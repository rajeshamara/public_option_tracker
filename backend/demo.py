"""Deterministic fictional portfolio fixtures; no credentials, storage, or network."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo('America/New_York')
PRICES = {'DEMO': 102.0, 'SAMPLE': 49.9, 'FICTION': 200.5}


def position_snapshot(now=None):
    now = now or datetime.now(EASTERN)
    today = now.astimezone(EASTERN).date()
    # Symbol, calendar DTE, type, strike, side, quantity. All values are invented.
    examples = [
        ('DEMO', 0, 'CALL', 100, 'Short', 2),
        ('SAMPLE', 0, 'PUT', 50, 'Short', 1),
        ('DEMO', 1, 'PUT', 100, 'Short', 1),
        ('SAMPLE', 1, 'PUT', 50, 'Short', 2),
        ('DEMO', 2, 'CALL', 105, 'Long', 1),
        ('FICTION', 3, 'CALL', 200, 'Short', 1),
        ('SAMPLE', 7, 'CALL', 50, 'Long', 2),
        ('DEMO', 7, 'CALL', 102, 'Long', 1),
        ('UNQUOTED', 14, 'CALL', 30, 'Short', 1),
        ('FICTION', 30, 'PUT', 205, 'Short', 1),
        ('DEMO', -1, 'CALL', 95, 'Short', 1),
    ]
    rows = []
    for symbol, days, kind, strike, side, quantity in examples:
        expiry = today + timedelta(days=days)
        rows.append({
            'account': 'Demo account',
            'symbol': f'{symbol} {expiry:%y%m%d}{kind[0]}{strike * 1000:08d}',
            'description': f'Fictional {symbol} {kind.lower()} — synthetic demo data',
            'underlying': symbol, 'type': kind, 'expiration': expiry.isoformat(),
            'strike': strike, 'side': side, 'quantity': quantity,
        })
    return {'positions': rows, 'accounts_count': 1, 'received_at': int(now.timestamp() * 1000)}


def quote_snapshot(symbol, now=None):
    price = PRICES.get(symbol)
    if price is None:
        return None
    now = now or datetime.now(EASTERN)
    timestamp = int(now.timestamp() * 1000)
    return {
        'symbol': symbol, 'description': f'Fictional {symbol} — synthetic demo quote',
        'last': price, 'bid': round(price - 0.05, 2), 'ask': round(price + 0.05, 2),
        'quote_time': timestamp, 'trade_time': timestamp,
        'realtime': None, 'received_at': timestamp,
    }
