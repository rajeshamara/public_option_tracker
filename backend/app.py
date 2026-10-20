from pathlib import Path
import asyncio
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from near_strike import load_rules

CALLBACK = 'https://127.0.0.1:8182/callback'
DEMO_MODE = os.getenv('OPTIONTRACKER_DEMO') == '1'
if DEMO_MODE:
    CLIENT_ID, CLIENT_SECRET = '', ''
else:
    from config import load_credentials
    CLIENT_ID, CLIENT_SECRET = load_credentials()
DIST = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
pending = {}
import token_store
storage_error = False
try:
    sessions = {} if DEMO_MODE else token_store.load()
except (OSError, ValueError):
    sessions = {}
    storage_error = True
exchange_lock = asyncio.Lock()

@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method == 'POST':
        expected = f'{request.url.scheme}://{request.url.netloc}'
        if request.headers.get('origin') != expected or request.headers.get('x-optiontracker') != '1':
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Request must originate from OptionTracker.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

def prune():
    now = time.time()
    for store in (pending, sessions):
        for key in list(store):
            if store[key]['expires'] <= now:
                del store[key]

@app.get('/api/hello')
def hello():
    return {'message': 'OptionTracker: React is connected to the Python backend.'}

@app.get('/api/near-strike-rules')
def near_strike_rules():
    try:
        return load_rules()
    except ValueError as error:
        raise HTTPException(503, str(error)) from None

@app.get('/api/status')
async def status(request: Request):
    if DEMO_MODE:
        return dict(demo=True, configured=False, connected=True, secure=False,
                    session_saved=False, retryable=False,
                    message='Demo mode: fictional positions and prices. No brokerage connection or credentials are used.')
    prune()
    session_id = request.cookies.get('ot_session')
    connected = session_id in sessions
    renewal_error = None
    retryable = False
    if connected:
        try:
            await access_token(session_id)
        except HTTPException as error:
            connected = False
            renewal_error = error.detail
            retryable = error.status_code != 401
    configured = bool(CLIENT_ID and CLIENT_SECRET)
    secure = request.url.scheme == 'https'
    if renewal_error:
        message = renewal_error
    elif connected:
        message = 'Connected. Your session is saved with Windows encryption and access renews automatically.'
    elif not configured:
        message = 'The app is running. Add the Schwab app credentials to the backend to enable connection.'
    elif not secure:
        message = 'Credentials are configured. Start the HTTPS listener on port 8182 to connect to Schwab.'
    elif storage_error:
        message = 'The saved session could not be unlocked. Reconnect Schwab to save a new session.'
    else:
        message = 'Ready to connect. Schwab will open so you can sign in and authorize access.'
    # A failed renewal is a connection state, not a failed status request. The UI
    # must still be able to retry or reconnect without discarding a saved grant.
    return dict(demo=False, configured=configured, connected=connected, secure=secure,
                session_saved=session_id in sessions, retryable=retryable, message=message)

@app.post('/api/connect')
def connect(request: Request):
    if DEMO_MODE:
        raise HTTPException(403, 'Brokerage authorization is disabled in demo mode.')
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(503, 'Schwab credentials are not configured yet. The app is ready; the backend needs the Client ID and Client Secret from your developer app.')
    if str(request.base_url) != 'https://127.0.0.1:8182/':
        raise HTTPException(503, 'Open this app at https://127.0.0.1:8182 after setting up its trusted local HTTPS certificate.')
    prune()
    state = secrets.token_urlsafe(32)
    browser_nonce = secrets.token_urlsafe(32)
    pending[state] = {'nonce': browser_nonce, 'expires': time.time() + 600}
    from fastapi.responses import JSONResponse
    response = JSONResponse({'url': 'https://api.schwabapi.com/v1/oauth/authorize?' + urlencode({'client_id': CLIENT_ID, 'redirect_uri': CALLBACK, 'response_type': 'code', 'state': state})})
    response.set_cookie('ot_oauth', browser_nonce, max_age=600, httponly=True, secure=True, samesite='lax', path='/callback')
    return response

@app.get('/callback')
async def callback(request: Request):
    if DEMO_MODE:
        raise HTTPException(403, 'Brokerage authorization is disabled in demo mode.')
    prune()
    state = request.query_params.get('state', '')
    record = pending.get(state)
    nonce = request.cookies.get('ot_oauth', '')
    if not record or not secrets.compare_digest(record['nonce'], nonce):
        raise HTTPException(400, 'Invalid or expired connection attempt. Return to OptionTracker and connect again.')
    del pending[state]
    response = RedirectResponse('/?connection=failed', status_code=303)
    response.delete_cookie('ot_oauth', path='/callback', secure=True, httponly=True, samesite='lax')
    code = request.query_params.get('code')
    if request.query_params.get('error') or not code:
        return response
    try:
        async with exchange_lock, httpx.AsyncClient(timeout=20) as client:
            result = await client.post('https://api.schwabapi.com/v1/oauth/token', auth=(CLIENT_ID, CLIENT_SECRET), data={'grant_type':'authorization_code', 'code':code, 'redirect_uri':CALLBACK})
        if result.status_code != 200:
            return response
        token = result.json()
        if not token.get('access_token') or float(token.get('expires_in', 0)) <= 0:
            return response
        session = secrets.token_urlsafe(32)
        expires_in = int(token['expires_in'])
        previous = request.cookies.get('ot_session')
        if previous:
            sessions.pop(previous, None)
        sessions.clear()
        sessions[session] = {'token':token, 'expires':time.time() + 7*86400, 'access_expires':time.time() + expires_in}
        token_store.save(sessions)
        response.headers['location'] = '/?connection=success'
        response.set_cookie('ot_session', session, max_age=7*86400, httponly=True, secure=True, samesite='lax')
    except (httpx.HTTPError, ValueError, TypeError, OSError):
        pass
    return response

@app.get('/')
def index():
    if not (DIST / 'index.html').exists():
        raise HTTPException(503, 'Build the React frontend first: npm run build.')
    return FileResponse(DIST / 'index.html')

if (DIST / 'assets').exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

def persist():
    if DEMO_MODE:
        raise HTTPException(403, 'Session persistence is disabled in demo mode.')
    try:
        token_store.save(sessions)
    except OSError:
        raise HTTPException(503, 'Unable to save the encrypted session. Check access to the secrets folder.') from None

async def access_token(session_id, rejected_token=None):
    if DEMO_MODE:
        raise HTTPException(403, 'Brokerage access is disabled in demo mode.')
    # The lock prevents simultaneous dashboard quote requests rotating the token twice.
    async with exchange_lock:
        prune()
        session = sessions.get(session_id)
        if not session:
            raise HTTPException(401, 'Schwab requires authorization again. Please reconnect.')
        token = session['token']
        current = token['access_token']
        needs_refresh = session.get('access_expires', session['expires']) <= time.time() + 60
        if rejected_token is not None and rejected_token == current:
            needs_refresh = True
        if not needs_refresh:
            return current
        if not token.get('refresh_token'):
            sessions.pop(session_id, None)
            persist()
            raise HTTPException(401, 'Schwab requires authorization again. Please reconnect.')
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                result = await client.post('https://api.schwabapi.com/v1/oauth/token',
                    auth=(CLIENT_ID, CLIENT_SECRET),
                    data={'grant_type':'refresh_token', 'refresh_token':token['refresh_token']})
            data = result.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'Could not renew Schwab access. Your saved session is retained; try again shortly.') from None
        if not isinstance(data, dict):
            raise HTTPException(503, 'Schwab returned an incomplete renewal response. Your saved session is retained; try again shortly.')
        if result.status_code in (400, 401) and data.get('error') == 'invalid_grant':
            sessions.pop(session_id, None)
            persist()
            raise HTTPException(401, 'Schwab authorization expired or was revoked. Please reconnect.')
        if result.status_code != 200:
            # Do not echo Schwab's raw response: it may contain sensitive data.
            if data.get('error') == 'invalid_client':
                raise HTTPException(503, 'Schwab rejected the renewal credentials. Your saved session is retained. Retry or reconnect; if this continues, check the Schwab app credentials.')
            raise HTTPException(503, 'Schwab could not renew access. Your saved session is retained. Retry now or reconnect Schwab.')
        try:
            lifetime = float(data['expires_in'])
            if not data.get('access_token') or lifetime <= 0: raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise HTTPException(503, 'Schwab returned an incomplete renewal response.') from None
        session['token'] = {**token, **data}
        session['access_expires'] = time.time() + lifetime
        persist()
        return session['token']['access_token']

# Read-only Schwab data access. No arbitrary URLs or order endpoints are exposed.
async def schwab_get(request: Request, path: str, params=None):
    session_id = request.cookies.get('ot_session')
    token = await access_token(session_id)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            result = await client.get('https://api.schwabapi.com' + path, params=params,
                                      headers={'Authorization': 'Bearer ' + token})
            if result.status_code == 401:
                token = await access_token(session_id, rejected_token=token)
                result = await client.get('https://api.schwabapi.com' + path, params=params,
                                          headers={'Authorization': 'Bearer ' + token})
        if result.status_code == 401:
            sessions.pop(session_id, None)
            persist()
            raise HTTPException(401, 'Schwab authorization expired. Please reconnect.')
        if result.status_code == 403:
            raise HTTPException(403, 'Schwab denied access. Check the app product permissions and selected accounts.')
        if result.status_code == 429:
            raise HTTPException(429, 'Schwab rate limit reached. Wait before refreshing.')
        if result.status_code != 200:
            raise HTTPException(502, f'Schwab returned HTTP {result.status_code}. Please try again.')
        return result.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Unable to read a valid response from Schwab. Please try again.') from None

@app.get('/api/quote')
async def quote(request: Request, symbol: str = 'AAPL'):
    import re
    symbol = symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9.$/-]{1,20}', symbol):
        raise HTTPException(400, 'Enter one valid stock symbol, for example AAPL.')
    if DEMO_MODE:
        from demo import quote_snapshot
        result = quote_snapshot(symbol)
        if result is None:
            raise HTTPException(404, 'Demo quotes are available for DEMO, SAMPLE and FICTION only. UNQUOTED intentionally has no price.')
        return result
    data = await schwab_get(request, '/marketdata/v1/quotes', {'symbols':symbol})
    item = data.get(symbol) if isinstance(data, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get('quote'), dict):
        raise HTTPException(404, 'No quote returned for that symbol.')
    q = item['quote']
    return {'symbol':symbol, 'description':item.get('reference', {}).get('description'),
            'last':q.get('lastPrice'), 'bid':q.get('bidPrice'), 'ask':q.get('askPrice'),
            'quote_time':q.get('quoteTime'), 'trade_time':q.get('tradeTime'),
            'realtime':item.get('realtime'), 'received_at':int(time.time()*1000)}

def option_rows(accounts):
    import re
    from datetime import datetime
    rows = []
    for index, wrapper in enumerate(accounts):
        account = wrapper.get('securitiesAccount', {})
        # Account numbers and balances never leave the backend.
        label = f'Account {index + 1}'
        for position in account.get('positions', []) or []:
            instrument = position.get('instrument', {})
            if instrument.get('assetType') != 'OPTION':
                continue
            symbol = instrument.get('symbol', '')
            match = re.fullmatch(r'(.+?)\s*(\d{6})([CP])(\d{8})', symbol)
            expiry, strike, kind = None, None, instrument.get('putCall')
            underlying = instrument.get('underlyingSymbol')
            if match:
                try:
                    expiry = datetime.strptime(match[2], '%y%m%d').date().isoformat()
                    strike = int(match[4]) / 1000
                    kind = 'CALL' if match[3] == 'C' else 'PUT'
                    underlying = underlying or match[1].strip()
                except ValueError:
                    pass
            for direction, field in [('Long','longQuantity'), ('Short','shortQuantity')]:
                quantity = position.get(field, 0) or 0
                if quantity > 0:
                    rows.append({'account':label, 'symbol':symbol, 'description':instrument.get('description'),
                                 'underlying':underlying, 'type':kind, 'expiration':expiry, 'strike':strike,
                                 'side':direction, 'quantity':quantity})
    return sorted(rows, key=lambda row: (row['expiration'] or '9999', row['symbol'], row['account'], row['side']))

@app.get('/api/positions')
async def positions(request: Request):
    if DEMO_MODE:
        from demo import position_snapshot
        return position_snapshot()
    data = await schwab_get(request, '/trader/v1/accounts', {'fields':'positions'})
    if not isinstance(data, list) or not all(isinstance(a, dict) and isinstance(a.get('securitiesAccount'), dict) for a in data):
        raise HTTPException(502, 'Schwab returned an unexpected accounts response.')
    return {'positions':option_rows(data), 'accounts_count':len(data), 'received_at':int(time.time()*1000)}
