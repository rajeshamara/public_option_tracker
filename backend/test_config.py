"""Configuration must be portable and must never discover private credentials."""
import importlib.util
from pathlib import Path

import pytest
import config


def test_no_implicit_credential_file(monkeypatch):
    for key in ('SCHWAB_CLIENT_ID', 'SCHWAB_CLIENT_SECRET', 'SCHWAB_CONFIG_FILE'):
        monkeypatch.delenv(key, raising=False)
    def unexpected_read(*args, **kwargs):
        raise AssertionError('Credential file access must be explicit')
    monkeypatch.setattr(Path, 'read_text', unexpected_read)
    assert config.load_credentials() == ('', '')


def test_complete_environment_pair_overrides_file(monkeypatch):
    monkeypatch.setenv('SCHWAB_CLIENT_ID', ' example-id ')
    monkeypatch.setenv('SCHWAB_CLIENT_SECRET', ' example-secret ')
    monkeypatch.setenv('SCHWAB_CONFIG_FILE', 'missing-test-config.json')
    assert config.load_credentials() == ('example-id', 'example-secret')


def test_explicit_missing_file_fails_without_exposing_path(monkeypatch, tmp_path):
    monkeypatch.delenv('SCHWAB_CLIENT_ID', raising=False)
    monkeypatch.delenv('SCHWAB_CLIENT_SECRET', raising=False)
    path = tmp_path / 'private-config.json'
    monkeypatch.setenv('SCHWAB_CONFIG_FILE', str(path))
    with pytest.raises(RuntimeError) as error:
        config.load_credentials()
    assert str(path) not in str(error.value)


def test_runtime_files_share_configured_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('OPTIONTRACKER_DATA_DIR', str(tmp_path))
    spec = importlib.util.spec_from_file_location('isolated_config', config.__file__)
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    assert isolated.DATA_DIRECTORY == tmp_path
    assert isolated.TLS_DIRECTORY == tmp_path / 'tls'
