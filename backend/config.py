import json
import os
from pathlib import Path

DEFAULT_DATA = (Path(os.environ['LOCALAPPDATA']) / 'OptionTrackerShowcase'
                if os.name == 'nt' and os.environ.get('LOCALAPPDATA')
                else Path.home() / '.local' / 'share' / 'optiontracker-showcase')
DATA_DIRECTORY = Path(os.getenv('OPTIONTRACKER_DATA_DIR', str(DEFAULT_DATA))).expanduser()
TLS_DIRECTORY = DATA_DIRECTORY / 'tls'

def load_credentials():
    client_id = os.getenv('SCHWAB_CLIENT_ID', '').strip()
    client_secret = os.getenv('SCHWAB_CLIENT_SECRET', '').strip()
    if client_id and client_secret:
        return client_id, client_secret
    # Never discover credentials from another application or an implicit file.
    filename = os.getenv('SCHWAB_CONFIG_FILE', '').strip()
    if not filename:
        return client_id, client_secret
    path = Path(filename).expanduser()
    try:
        settings = json.loads(path.read_text(encoding='utf-8-sig'))['option_tracker']
        values = (settings['client_id'], settings['client_secret'])
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError()
        return tuple(value.strip() for value in values)
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('Schwab configuration must contain option_tracker.client_id and option_tracker.client_secret as nonempty strings.') from None
