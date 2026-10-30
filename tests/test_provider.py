"""Provider compatibility and safe failure diagnostics."""
import threading
from pathlib import Path
import pytest
from mathbank.provider import CodexProvider, diagnose


@pytest.mark.parametrize('log, expected', [
    ("error: unexpected argument '--ignore-user-config' found", '옵션 호환성'),
    ('Error: Unknown feature: browser_use', '옵션 호환성'),
    ('The model is not supported when using Codex with a ChatGPT account', '지정 모델'),
    ('model_not_found: secret-source-text', '지정 모델'),
    ('Unsupported value: reasoning_effort', '추론 옵션'),
    ('certificate verify failed', 'TLS'),
    ('Error loading config: TOML parse error', '설정'),
    ('refresh_token_reused', '로그인 세션'),
    ('Cannot find module node_modules/codex', '설치 파일'),
])
def test_known_failures_do_not_expose_raw_logs(log, expected):
    message = diagnose(log + '\nAuthorization: Bearer SECRET_TOKEN\nsource: PRIVATE_QUESTION')
    assert expected in message
    assert 'SECRET_TOKEN' not in message
    assert 'PRIVATE_QUESTION' not in message
    assert 'secret-source-text' not in message


def test_call_uses_config_overrides_for_optional_features(monkeypatch):
    import mathbank.provider as module
    provider = CodexProvider(enabled=True)
    monkeypatch.setattr(provider, 'status', lambda: (True, 'ok'))
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/fake/codex')
    calls = []
    class Process:
        returncode = 0
        def poll(self):
            return 0
    def spawn(args, **kwargs):
        calls.append(args)
        Path(args[args.index('--output-last-message') + 1]).write_text('{"ok":true}')
        return Process()
    monkeypatch.setattr(module, 'external_popen', spawn)
    assert provider.call('fixture', [], threading.Event()) == {'ok': True}
    args = calls[0]
    assert '--disable' not in args
    assert '--ignore-user-config' in args
    assert args[args.index('--sandbox') + 1] == 'read-only'
    for feature in ('shell_tool', 'unified_exec', 'apps', 'js_repl', 'multi_agent', 'browser_use'):
        assert f'features.{feature}=false' in args


def test_only_independent_reader_uses_separate_effort(monkeypatch):
    import mathbank.provider as module
    provider = CodexProvider(enabled=True, effort='high', reading_effort='medium')
    monkeypatch.setattr(provider, 'status', lambda: (True, 'ok'))
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/fake/codex')
    calls = []
    class Process:
        returncode = 0
        def poll(self): return 0
    def spawn(args, **kwargs):
        calls.append(args)
        Path(args[args.index('--output-last-message') + 1]).write_text('{"ok":true}')
        return Process()
    monkeypatch.setattr(module, 'external_popen', spawn)
    provider.read('read', [])
    provider.call('solve', [])
    assert 'model_reasoning_effort="medium"' in calls[0]
    assert 'model_reasoning_effort="high"' in calls[1]
    assert provider.effort == 'high'


def test_token_usage_unknown_is_not_zero():
    from mathbank.provider import token_usage
    assert token_usage('tokens used\n12,345\n') == 12345
    assert token_usage('tokens used\n0\n') == 0
    assert token_usage('source text says 999 tokens') is None


@pytest.mark.parametrize('limit', [1, 2])
def test_shared_call_bound_includes_read_requests(monkeypatch, limit):
    import time
    from concurrent.futures import ThreadPoolExecutor
    provider = CodexProvider()
    provider.set_concurrency(limit)
    active = peak = 0
    lock = threading.Lock()
    def request(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.02)
        with lock: active -= 1
        return {}
    monkeypatch.setattr(provider, '_call', request)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(provider.read if i % 2 else provider.call, 'test', []) for i in range(6)]
        for future in futures: future.result()
    assert peak <= limit and active == 0


def test_cancel_while_waiting_for_request_slot():
    from mathbank.provider import Cancelled
    provider = CodexProvider()
    provider.set_concurrency(1)
    provider._slots.acquire()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        provider.read('test', [], cancel)
    provider._slots.release()
