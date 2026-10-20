import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer
import uvicorn
from config import TLS_DIRECTORY

if __name__ == '__main__':
    demo = os.getenv('OPTIONTRACKER_DEMO', '0') == '1'
    cert = None if demo else os.getenv('OPTIONTRACKER_TLS_CERT')
    key = None if demo else os.getenv('OPTIONTRACKER_TLS_KEY')
    if not demo and not cert and not key:
        cert = str(TLS_DIRECTORY / 'localhost.crt') if (TLS_DIRECTORY / 'localhost.crt').exists() else None
        key = str(TLS_DIRECTORY / 'localhost.key') if (TLS_DIRECTORY / 'localhost.key').exists() else None
    if bool(cert) != bool(key):
        raise SystemExit('Set both OPTIONTRACKER_TLS_CERT and OPTIONTRACKER_TLS_KEY.')
    if cert and (not Path(cert).is_file() or not Path(key).is_file()):
        raise SystemExit('The configured TLS files do not exist.')
    port = 8182 if cert else 8181
    url = f'{"https" if cert else "http"}://127.0.0.1:{port}'
    print(f'OptionTracker: {url}')
    Timer(1.5, lambda: webbrowser.open(url)).start()
    # Avoid Windows Proactor's connection-reset error during TLS socket cleanup.
    # Use an explicit factory: recent Uvicorn versions bypass event-loop policies.
    loop = 'asyncio:SelectorEventLoop' if sys.platform == 'win32' else 'auto'
    uvicorn.run('app:app', host='127.0.0.1', port=port, ssl_certfile=cert, ssl_keyfile=key, access_log=False, proxy_headers=False, loop=loop)
