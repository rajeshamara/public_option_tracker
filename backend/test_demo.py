"""The portfolio preview must never touch a brokerage account or saved session."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

import config
import token_store
from demo import position_snapshot, quote_snapshot


@pytest.fixture
def demo_app(monkeypatch):
    monkeypatch.setenv('OPTIONTRACKER_DEMO', '1')
    blocked = []
    for target, name in ((config, 'load_credentials'), (token_store, 'load'),
                         (token_store, 'save'), (httpx, 'AsyncClient')):
        guard = Mock(side_effect=AssertionError(f'Demo must not call {name}'))
        monkeypatch.setattr(target, name, guard)
        blocked.append(guard)
    spec = importlib.util.spec_from_file_location('isolated_demo_app', Path(__file__).with_name('app.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for guard in blocked:
        guard.assert_not_called()


def test_demo_import_and_routes_are_isolated(demo_app):
    with TestClient(demo_app.app, base_url='http://127.0.0.1:8181') as client:
        status = client.get('/api/status').json()
        assert status['demo'] and status['connected']
        assert not status['configured'] and not status['session_saved']
        snapshot = client.get('/api/positions').json()
        assert snapshot['accounts_count'] == 1
        assert len(snapshot['positions']) == 11
        assert {row['account'] for row in snapshot['positions']} == {'Demo account'}
        quote = client.get('/api/quote?symbol=demo').json()
        assert quote['last'] == 102 and quote['realtime'] is None
        for symbol in ('UNQUOTED', 'AAPL'):
            result = client.get('/api/quote', params={'symbol': symbol})
            assert result.status_code == 404
            assert 'Demo quotes' in result.json()['detail']
        headers = {'origin': 'http://127.0.0.1:8181', 'X-OptionTracker': '1'}
        assert client.post('/api/connect', headers=headers).status_code == 403
        assert client.get('/callback?state=unused&code=unused').status_code == 403
        assert not client.cookies


@pytest.mark.parametrize('instant,expected_day', [
    ('2026-07-01T02:00:00+00:00', '2026-06-30'),
    ('2026-12-01T03:00:00+00:00', '2026-11-30'),
])
def test_demo_expirations_follow_eastern_date(instant, expected_day):
    snapshot = position_snapshot(datetime.fromisoformat(instant))
    assert snapshot['positions'][0]['expiration'] == expected_day
    expirations = [row['expiration'] for row in snapshot['positions']]
    assert min(expirations) < expected_day < max(expirations)
    assert {'Long', 'Short'} == {row['side'] for row in snapshot['positions']}
    assert {'CALL', 'PUT'} == {row['type'] for row in snapshot['positions']}


def test_demo_prices_are_fixed_and_missing_quote_is_explicit():
    first = quote_snapshot('DEMO', datetime(2026, 1, 1, tzinfo=timezone.utc))
    later = quote_snapshot('DEMO', datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert first['last'] == later['last'] == 102
    assert first['received_at'] < later['received_at']
    assert quote_snapshot('UNQUOTED') is None
