from src.retrieval.generator import OllamaGenerator


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_generate_returns_text(monkeypatch):
    def _fake_urlopen(_req, timeout=0):
        return _Resp(b'{"message":{"content":"ok"}}')

    monkeypatch.setattr("src.retrieval.generator.urlopen", _fake_urlopen)
    generator = OllamaGenerator()
    out = generator.generate("q", ["ctx"])
    assert out == "ok"
