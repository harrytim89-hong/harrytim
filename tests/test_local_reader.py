import json
import threading
import pytest
from mathbank.local_reader import read
from mathbank.provider import ProviderError, Cancelled, CodexProvider


def test_local_reader_sends_only_source_and_uses_loopback(monkeypatch, tmp_path):
    import mathbank.local_reader as module
    image = tmp_path / 'source.png'
    image.write_bytes(b'png')
    calls = []
    result = dict(text='$x=1$', choices=[], uncertain=False)
    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ('127.0.0.1', 11434, 30)
        def request(self, method, path, payload, headers):
            calls.append(json.loads(payload))
        def getresponse(self): return self
        status = 200
        def read(self, size):
            return json.dumps(dict(done=True, message=dict(content=json.dumps(result)))).encode()
        def close(self): pass
    monkeypatch.setattr(module.http.client, 'HTTPConnection', Connection)
    assert read('vision', 'read only', [image], threading.Event()) == result
    assert len(calls[0]['messages']) == 1
    assert 'candidate' not in str(calls[0])
    assert calls[0]['options']['num_ctx'] == 4096


def test_local_read_failure_does_not_fall_back_to_cloud(monkeypatch):
    import mathbank.local_reader as module
    provider = CodexProvider(enabled=True)
    provider.local_model = 'vision'
    def fail(*args): raise ProviderError('local failure')
    monkeypatch.setattr(module, 'read', fail)
    monkeypatch.setattr(provider, 'status', lambda: pytest.fail('cloud fallback'))
    with pytest.raises(ProviderError, match='local failure'):
        provider.read('read only', [], threading.Event())


def test_cancelled_local_read_sends_nothing():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled): read('vision', 'read', [], cancel)
