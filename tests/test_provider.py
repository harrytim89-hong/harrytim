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
