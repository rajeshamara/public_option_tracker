"""Keep collection and tests isolated from a developer's live credentials."""
import os
from pathlib import Path
import tempfile


_sandbox = None
_original_environment = {}
_managed_names = (
    'SCHWAB_CLIENT_ID',
    'SCHWAB_CLIENT_SECRET',
    'SCHWAB_CONFIG_FILE',
    'OPTIONTRACKER_DATA_DIR',
    'OPTIONTRACKER_TLS_CERT',
    'OPTIONTRACKER_TLS_KEY',
    'OPTIONTRACKER_DEMO',
)


def pytest_configure(config):
    """Run before test modules import the application or its configuration."""
    global _sandbox
    _sandbox = tempfile.TemporaryDirectory(prefix='optiontracker-tests-')
    _original_environment.update({name: os.environ.get(name) for name in _managed_names})
    for name in _managed_names:
        os.environ.pop(name, None)
    root = Path(_sandbox.name)
    os.environ['OPTIONTRACKER_DATA_DIR'] = str(root / 'data')
    os.environ['SCHWAB_CONFIG_FILE'] = str(root / 'no-credentials.json')
    os.environ['OPTIONTRACKER_DEMO'] = '0'


def pytest_unconfigure(config):
    for name, value in _original_environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if _sandbox is not None:
        _sandbox.cleanup()
