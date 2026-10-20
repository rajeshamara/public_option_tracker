"""Exercise the launcher without loading credentials or opening a browser/server."""
import asyncio
from pathlib import Path
import runpy
import sys
import threading
from types import ModuleType
from unittest.mock import Mock
import webbrowser

import pytest
import uvicorn


RUN_PATH = Path(__file__).with_name('run.py')


@pytest.mark.parametrize('platform, expected_loop', [
    ('win32', 'asyncio:SelectorEventLoop'),
    ('linux', 'auto'),
])
@pytest.mark.parametrize('secure', [False, True], ids=['http', 'https'])
def test_launcher_selects_loop_and_preserves_listener_settings(
    monkeypatch, tmp_path, platform, expected_loop, secure,
):
    # Supply an isolated TLS directory and fail if the launcher loads credentials.
    config = ModuleType('config')
    config.TLS_DIRECTORY = tmp_path / 'tls'
    config.TLS_DIRECTORY.mkdir()
    config.load_credentials = Mock(side_effect=AssertionError('Credentials must not be loaded'))
    monkeypatch.setitem(sys.modules, 'config', config)
    monkeypatch.delenv('OPTIONTRACKER_TLS_CERT', raising=False)
    monkeypatch.delenv('OPTIONTRACKER_TLS_KEY', raising=False)
    cert = config.TLS_DIRECTORY / 'localhost.crt'
    key = config.TLS_DIRECTORY / 'localhost.key'
    if secure:
        cert.write_text('test certificate placeholder', encoding='utf-8')
        key.write_text('test key placeholder', encoding='utf-8')

    run = Mock()
    timer = Mock()
    browser = Mock()
    monkeypatch.setattr(uvicorn, 'run', run)
    monkeypatch.setattr(threading, 'Timer', timer)
    monkeypatch.setattr(webbrowser, 'open', browser)
    monkeypatch.setattr(sys, 'platform', platform)

    runpy.run_path(str(RUN_PATH), run_name='__main__')

    run.assert_called_once_with(
        'app:app', host='127.0.0.1', port=8182 if secure else 8181,
        ssl_certfile=str(cert) if secure else None,
        ssl_keyfile=str(key) if secure else None,
        access_log=False, proxy_headers=False, loop=expected_loop,
    )
    config.load_credentials.assert_not_called()
    timer.assert_called_once()
    assert timer.call_args.args[0] == 1.5
    timer.return_value.start.assert_called_once_with()
    browser.assert_not_called()
    timer.call_args.args[1]()
    browser.assert_called_once_with(
        'https://127.0.0.1:8182' if secure else 'http://127.0.0.1:8181'
    )


def test_installed_uvicorn_resolves_and_runs_selector_loop_factory():
    # Custom loop factories require Uvicorn >= 0.36. Exercise the installed
    # version's resolver, rather than assuming it accepts the import string.
    config = uvicorn.Config('unused:app', loop='asyncio:SelectorEventLoop', log_config=None)
    factory = config.get_loop_factory()
    assert factory is asyncio.SelectorEventLoop

    async def scheduled_result():
        loop = asyncio.get_running_loop()
        assert isinstance(loop, asyncio.SelectorEventLoop)
        result = loop.create_future()
        loop.call_soon(result.set_result, 'selector running')
        return await result

    with asyncio.Runner(loop_factory=factory) as runner:
        assert runner.run(scheduled_result()) == 'selector running'


@pytest.mark.parametrize('configured', [(), ('CERT',), ('KEY',), ('CERT', 'KEY')])
def test_demo_ignores_default_and_explicit_tls(monkeypatch, tmp_path, configured):
    config = ModuleType('config')
    config.TLS_DIRECTORY = tmp_path / 'tls'
    config.TLS_DIRECTORY.mkdir()
    for filename in ('localhost.crt', 'localhost.key'):
        (config.TLS_DIRECTORY / filename).write_text('synthetic TLS placeholder', encoding='utf-8')
    config.load_credentials = Mock(side_effect=AssertionError('Credentials must not be loaded'))
    monkeypatch.setitem(sys.modules, 'config', config)
    monkeypatch.setenv('OPTIONTRACKER_DEMO', '1')
    for suffix in ('CERT', 'KEY'):
        variable = f'OPTIONTRACKER_TLS_{suffix}'
        if suffix in configured:
            monkeypatch.setenv(variable, str(tmp_path / f'nonexistent-{suffix.lower()}'))
        else:
            monkeypatch.delenv(variable, raising=False)
    run, timer, browser = Mock(), Mock(), Mock()
    monkeypatch.setattr(uvicorn, 'run', run)
    monkeypatch.setattr(threading, 'Timer', timer)
    monkeypatch.setattr(webbrowser, 'open', browser)

    runpy.run_path(str(RUN_PATH), run_name='__main__')

    run.assert_called_once()
    assert run.call_args.kwargs['host'] == '127.0.0.1'
    assert run.call_args.kwargs['port'] == 8181
    assert run.call_args.kwargs['ssl_certfile'] is None
    assert run.call_args.kwargs['ssl_keyfile'] is None
    config.load_credentials.assert_not_called()
    timer.call_args.args[1]()
    browser.assert_called_once_with('http://127.0.0.1:8181')


@pytest.mark.parametrize('provided, fallback', [
    ('CERT', 'localhost.key'),
    ('KEY', 'localhost.crt'),
])
def test_partial_explicit_tls_cannot_mix_with_defaults(monkeypatch, tmp_path, provided, fallback):
    config = ModuleType('config')
    config.TLS_DIRECTORY = tmp_path / 'tls'
    config.TLS_DIRECTORY.mkdir()
    (config.TLS_DIRECTORY / fallback).write_text('synthetic default TLS placeholder', encoding='utf-8')
    explicit = tmp_path / f'explicit-{provided.lower()}'
    explicit.write_text('synthetic explicit TLS placeholder', encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'config', config)
    monkeypatch.setenv('OPTIONTRACKER_DEMO', '0')
    for suffix in ('CERT', 'KEY'):
        monkeypatch.delenv(f'OPTIONTRACKER_TLS_{suffix}', raising=False)
    monkeypatch.setenv(f'OPTIONTRACKER_TLS_{provided}', str(explicit))
    run, timer, browser = Mock(), Mock(), Mock()
    monkeypatch.setattr(uvicorn, 'run', run)
    monkeypatch.setattr(threading, 'Timer', timer)
    monkeypatch.setattr(webbrowser, 'open', browser)

    with pytest.raises(SystemExit, match='Set both OPTIONTRACKER_TLS_CERT and OPTIONTRACKER_TLS_KEY'):
        runpy.run_path(str(RUN_PATH), run_name='__main__')

    run.assert_not_called()
    timer.assert_not_called()
    browser.assert_not_called()
