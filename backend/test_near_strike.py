import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
import near_strike


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    path = tmp_path / 'near-strike.json'
    monkeypatch.setattr(near_strike, 'RULES_PATH', path)
    return path


def test_rules_preserve_both_distances_and_reload_edits(rules_file):
    rules = {'default': {'$': 3, '%': 0.5, 'use': '%'},
             'SPY': {'$': 3, '%': 0.25, 'use': '$'},
             'BRK/B': {'$': 0, '%': 0, 'use': '%'}}
    rules_file.write_text(json.dumps(rules), encoding='utf-8-sig')
    assert near_strike.load_rules() == rules
    rules['SPY']['use'] = '%'
    rules_file.write_text(json.dumps(rules), encoding='utf-8')
    assert near_strike.load_rules() == rules


def test_symbol_keys_are_normalized(rules_file):
    rules = {'default': {'$': 3, '%': 0.5, 'use': '%'},
             'spy': {'$': 3, '%': 0.25, 'use': '$'},
             'brk/b': {'$': 2, '%': 0.5, 'use': '%'}}
    rules_file.write_text(json.dumps(rules), encoding='utf-8')
    assert near_strike.load_rules() == {'default': rules['default'], 'SPY': rules['spy'], 'BRK/B': rules['brk/b']}


@pytest.mark.parametrize('value', [True, False, -0.1, '0.5', None, [], {},
                                   float('nan'), float('inf'), -float('inf'), 10 ** 400])
@pytest.mark.parametrize('key', ['$', '%'])
def test_invalid_distances_reject_entire_file(rules_file, key, value):
    rules = {'default': {'$': 3, '%': 0.5, 'use': '%'},
             'SPY': {'$': 3, '%': 0.5, 'use': '%'}}
    rules['SPY'][key] = value
    rules_file.write_text(json.dumps(rules), encoding='utf-8')
    with pytest.raises(ValueError, match='near-strike.json'):
        near_strike.load_rules()


@pytest.mark.parametrize('rules', [
    [], None, {}, {'SPY': {'$': 3, '%': 0.5, 'use': '%'}},
    {'default': None}, {'default': {'%': 0.5, 'use': '%'}},
    {'default': {'$': 3, '%': 0.5, 'use': '%', 'extra': 1}},
    {'default': {'$': 3, '%': 0.5, 'use': 'price'}},
    {'default': {'$': 3, '%': 0.5, 'use': []}},
    {'default': {'$': 3, '%': 0.5, 'use': True}},
    {'default': {'$': 3, '%': 0.5, 'use': '%'}, 'spy': {'$': 3, '%': 0.5, 'use': '%'},
     'SPY': {'$': 2, '%': 0.25, 'use': '$'}},
    {'default': {'$': 3, '%': 0.5, 'use': '%'}, 'bad symbol': {'$': 3, '%': 0.5, 'use': '%'}},
    {'default': {'$': 3, '%': 0.5, 'use': '%'}, 'DEFAULT': {'$': 3, '%': 0.25, 'use': '%'}},
])
def test_invalid_structure_rejected(rules_file, rules):
    rules_file.write_text(json.dumps(rules), encoding='utf-8')
    with pytest.raises(ValueError, match='near-strike.json'):
        near_strike.load_rules()


@pytest.mark.parametrize('contents', [b'{invalid secret contents', b'\xff',
    b'{"default":{"$":3,"%":0.5,"use":"%","use":"$"}}'])
def test_unreadable_json_has_safe_errors(rules_file, contents):
    rules_file.write_bytes(contents)
    with pytest.raises(ValueError, match='near-strike.json') as error:
        near_strike.load_rules()
    assert 'secret contents' not in str(error.value)


def test_missing_file_has_safe_error(rules_file):
    with pytest.raises(ValueError, match='Could not read near-strike.json'):
        near_strike.load_rules()


def test_endpoint_reloads_without_brokerage_or_session(rules_file):
    import config
    import token_store
    with patch.object(config, 'load_credentials', return_value=('', '')), \
         patch.object(token_store, 'load', return_value={}):
        import app as module
    rules = {'default': {'$': 3, '%': 0.5, 'use': '%'}}
    client = TestClient(module.app)
    with patch.object(module, 'schwab_get', AsyncMock()) as broker:
        rules_file.write_text(json.dumps(rules), encoding='utf-8')
        response = client.get('/api/near-strike-rules')
        assert response.status_code == 200
        assert response.json() == rules
        assert response.headers['cache-control'] == 'no-store'
        rules['SPY'] = {'$': 3, '%': 0.25, 'use': '$'}
        rules_file.write_text(json.dumps(rules), encoding='utf-8')
        assert client.get('/api/near-strike-rules').json() == rules
        rules_file.write_text('{invalid private contents', encoding='utf-8')
        failed = client.get('/api/near-strike-rules')
        assert failed.status_code == 503
        assert 'near-strike.json' in failed.json()['detail']
        assert 'private contents' not in failed.text
        rules_file.unlink()
        assert client.get('/api/near-strike-rules').status_code == 503
        broker.assert_not_called()
