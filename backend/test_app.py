import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parent))
import config
import token_store
original_save = token_store.save
with patch.object(config, 'load_credentials', return_value=('', '')), \
     patch.object(token_store, 'load', return_value={}):
    import app as module
import pytest

# All accounts, positions, credentials and token strings below are synthetic.
@pytest.fixture(autouse=True)
def isolated_sessions():
    module.sessions.clear()
    module.pending.clear()
    with patch.object(token_store, 'save'):
        yield
    module.sessions.clear()


BASE = 'https://127.0.0.1:8182'
HEADERS = {'origin':BASE, 'X-OptionTracker':'1'}

def test_hello_and_missing_credentials():
    with patch.object(module, 'CLIENT_ID', ''), patch.object(module, 'CLIENT_SECRET', ''):
        client = TestClient(module.app, base_url=BASE)
        assert 'OptionTracker' in client.get('/api/hello').json()['message']
        assert not client.get('/api/status').json()['configured']
        assert client.post('/api/connect', headers=HEADERS).status_code == 503

def test_cross_origin_and_forged_callback_are_rejected():
    client = TestClient(module.app, base_url=BASE)
    assert client.post('/api/connect', headers={'origin':'https://evil.example','X-OptionTracker':'1'}).status_code == 403
    assert client.get('/callback?state=forged&code=secret').status_code == 400

def test_successful_exchange_is_browser_bound_and_one_use():
    with patch.object(module, 'CLIENT_ID', 'test-id'), patch.object(module, 'CLIENT_SECRET', 'test-secret'):
        client = TestClient(module.app, base_url=BASE)
        from urllib.parse import urlparse, parse_qs
        result = client.post('/api/connect', headers=HEADERS)
        state = parse_qs(urlparse(result.json()['url']).query)['state'][0]
        stranger = TestClient(module.app, base_url=BASE)
        assert stranger.get('/callback', params={'state':state,'code':'code'}).status_code == 400
        reply = httpx.Response(200, json={'access_token':'private-token','expires_in':1800})
        with patch.object(httpx.AsyncClient, 'post', AsyncMock(return_value=reply)) as exchange:
            response = client.get('/callback', params={'state':state,'code':'code'}, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers['location'] == '/?connection=success'
            assert exchange.call_count == 1
        assert client.get('/api/status').json()['connected']
        assert 'private-token' not in client.get('/api/status').text
        assert client.get('/callback', params={'state':state,'code':'code'}).status_code == 400

def test_failed_exchange_does_not_connect():
    with patch.object(module, 'CLIENT_ID', 'test-id'), patch.object(module, 'CLIENT_SECRET', 'test-secret'):
        client = TestClient(module.app, base_url=BASE)
        from urllib.parse import urlparse, parse_qs
        url = client.post('/api/connect', headers=HEADERS).json()['url']
        state = parse_qs(urlparse(url).query)['state'][0]
        with patch.object(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(401))):
            result = client.get('/callback', params={'state':state,'code':'bad'}, follow_redirects=False)
        assert result.headers['location'] == '/?connection=failed'
        assert not client.get('/api/status').json()['connected']

def test_json_configuration(tmp_path, monkeypatch):
    import json
    import config
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'option_tracker': {'client_id':'example-id', 'client_secret':'example-secret'}}))
    monkeypatch.delenv('SCHWAB_CLIENT_ID', raising=False)
    monkeypatch.delenv('SCHWAB_CLIENT_SECRET', raising=False)
    monkeypatch.setenv('SCHWAB_CONFIG_FILE', str(path))
    assert config.load_credentials() == ('example-id', 'example-secret')
    path.write_text('{invalid')
    import pytest
    with pytest.raises(RuntimeError, match='configuration must contain'):
        config.load_credentials()

def test_option_rows_preserve_legs_and_hide_accounts():
    data = [{'securitiesAccount':{'accountNumber':'secret-account','positions':[
        {'instrument':{'assetType':'EQUITY','symbol':'AAPL'},'longQuantity':10},
        {'instrument':{'assetType':'OPTION','symbol':'AAPL  260925P00200000'},'shortQuantity':2,'longQuantity':1},
        {'instrument':{'assetType':'OPTION','symbol':'NONSTANDARD'},'longQuantity':1}]}}]
    rows = module.option_rows(data)
    assert len(rows) == 3
    assert rows[0]['expiration'] == '2026-09-25'
    assert rows[0]['strike'] == 200
    assert {r['side'] for r in rows[:2]} == {'Long','Short'}
    assert rows[2]['expiration'] is None
    assert 'secret-account' not in str(rows)

def test_data_routes_require_session():
    client = TestClient(module.app, base_url=BASE)
    assert client.get('/api/quote?symbol=AAPL').status_code == 401
    assert client.get('/api/positions').status_code == 401

def test_quote_and_positions_mapping():
    client = TestClient(module.app, base_url=BASE)
    import time
    module.sessions['data-test']={'token':{'access_token':'test'},'expires':time.time()+300}
    client.cookies.set('ot_session','data-test')
    payload={'AAPL':{'quote':{'lastPrice':200,'bidPrice':199,'askPrice':201,'quoteTime':1000},'realtime':False}}
    with patch.object(httpx.AsyncClient,'get',AsyncMock(return_value=httpx.Response(200,json=payload))):
        data=client.get('/api/quote?symbol=aapl').json()
        assert data['last']==200 and data['realtime'] is False
    with patch.object(httpx.AsyncClient,'get',AsyncMock(return_value=httpx.Response(200,json=[{'securitiesAccount':{'positions':[]}}]))):
        assert client.get('/api/positions').json()['positions']==[]
    with patch.object(httpx.AsyncClient,'get',AsyncMock(return_value=httpx.Response(403))):
        assert client.get('/api/positions').status_code==403
    with patch.object(httpx.AsyncClient,'get',AsyncMock(return_value=httpx.Response(401))):
        assert client.get('/api/positions').status_code==401
    assert not client.get('/api/status').json()['connected']

def test_refresh_rotates_and_saves_without_extending_authorization():
    import time, asyncio
    expiry=time.time()+5000
    module.sessions['saved']={'token':{'access_token':'old','refresh_token':'refresh'},'expires':expiry,'access_expires':0}
    reply=httpx.Response(200,json={'access_token':'new','refresh_token':'rotated','expires_in':1800})
    async def run():
        return await asyncio.gather(module.access_token('saved'),module.access_token('saved'))
    with patch.object(httpx.AsyncClient,'post',AsyncMock(return_value=reply)) as post:
        assert asyncio.run(run())==['new','new']
        assert post.call_count==1
    assert module.sessions['saved']['token']['refresh_token']=='rotated'
    assert module.sessions['saved']['expires']==expiry
    token_store.save.assert_called_once()

def test_temporary_failure_keeps_saved_authorization():
    import asyncio,time
    module.sessions['saved']={'token':{'access_token':'old','refresh_token':'refresh'},'expires':time.time()+5000,'access_expires':0}
    with patch.object(httpx.AsyncClient,'post',AsyncMock(return_value=httpx.Response(503,json={}))):
        with pytest.raises(module.HTTPException) as e: asyncio.run(module.access_token('saved'))
    assert e.value.status_code==503
    assert 'saved' in module.sessions

@pytest.mark.parametrize('status_code', [400, 401])
def test_revoked_refresh_clears_authorization(status_code):
    import asyncio,time
    module.sessions['saved']={'token':{'access_token':'old','refresh_token':'refresh'},'expires':time.time()+5000,'access_expires':0}
    with patch.object(httpx.AsyncClient,'post',AsyncMock(return_value=httpx.Response(status_code,json={'error':'invalid_grant'}))):
        with pytest.raises(module.HTTPException) as e: asyncio.run(module.access_token('saved'))
    assert e.value.status_code==401
    assert 'saved' not in module.sessions

@pytest.mark.parametrize('reply', [
    httpx.Response(503, json={'error_description': 'private-upstream-detail'}),
    httpx.Response(429, json={}),
    httpx.Response(401, json={'error': 'invalid_client'}),
    httpx.Response(502, text='upstream unavailable'),
    httpx.Response(200, json=['unexpected response']),
    httpx.Response(200, text='null'),
])
def test_status_keeps_recovery_available_after_renewal_failure(reply):
    import time
    saved = {'token': {'access_token': 'old-private-token', 'refresh_token': 'private-refresh'},
             'expires': time.time() + 5000, 'access_expires': 0}
    module.sessions['saved'] = saved
    client = TestClient(module.app, base_url=BASE)
    client.cookies.set('ot_session', 'saved')
    with patch.object(httpx.AsyncClient, 'post', AsyncMock(return_value=reply)):
        response = client.get('/api/status')
    assert response.status_code == 200
    data = response.json()
    assert data['connected'] is False
    assert data['session_saved'] is True
    assert data['retryable'] is True
    assert data['message']
    assert module.sessions['saved'] == saved
    token_store.save.assert_not_called()
    assert 'private' not in response.text


def test_status_recovers_after_temporary_network_failure():
    import time
    module.sessions['saved'] = {'token': {'access_token': 'old', 'refresh_token': 'refresh'},
                                'expires': time.time() + 5000, 'access_expires': 0}
    client = TestClient(module.app, base_url=BASE)
    client.cookies.set('ot_session', 'saved')
    reply = httpx.Response(200, json={'access_token': 'new', 'refresh_token': 'rotated', 'expires_in': 1800})
    with patch.object(httpx.AsyncClient, 'post', AsyncMock(side_effect=[httpx.ReadTimeout('timeout'), reply])) as post:
        failed = client.get('/api/status').json()
        assert failed['retryable'] and failed['session_saved'] and not failed['connected']
        recovered = client.get('/api/status').json()
        assert recovered['connected'] and recovered['session_saved'] and not recovered['retryable']
        assert post.call_count == 2
    with patch.object(httpx.AsyncClient, 'get', AsyncMock(return_value=httpx.Response(200, json=[]))):
        assert client.get('/api/positions').status_code == 200
    assert module.sessions['saved']['token']['refresh_token'] == 'rotated'
    token_store.save.assert_called_once()


def test_status_explains_revocation_and_allows_reconnect():
    import time
    module.sessions['saved'] = {'token': {'access_token': 'old', 'refresh_token': 'refresh'},
                                'expires': time.time() + 5000, 'access_expires': 0}
    client = TestClient(module.app, base_url=BASE)
    client.cookies.set('ot_session', 'saved')
    with patch.object(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(400, json={'error': 'invalid_grant'}))):
        response = client.get('/api/status')
    assert response.status_code == 200
    data = response.json()
    assert not data['connected'] and not data['session_saved'] and not data['retryable']
    assert 'reconnect' in data['message'].lower()
    with patch.object(module, 'CLIENT_ID', 'test-id'), patch.object(module, 'CLIENT_SECRET', 'test-secret'):
        assert client.post('/api/connect', headers=HEADERS).status_code == 200


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows DPAPI storage')
def test_dpapi_roundtrip_and_reload(tmp_path):
    # Exercise real encryption, isolated from the live secrets file.
    path=tmp_path/'session.dpapi'
    data={'browser-session':{'token':{'access_token':'sensitive-test-value','refresh_token':'refresh-test'},'expires':9999999999}}
    with patch.object(token_store,'PATH',path), patch.object(token_store,'save',wraps=original_save):
        token_store.save(data)
        assert b'sensitive-test-value' not in path.read_bytes()
        assert token_store.load()==data
        path.write_bytes(b'invalid ciphertext')
        with pytest.raises(OSError): token_store.load()
