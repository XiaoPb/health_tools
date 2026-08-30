from types import SimpleNamespace

from health_tools import cli


class _Stream:
    encoding = "cp1252"

    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_configure_windows_stdio_switches_legacy_streams_to_utf8(monkeypatch):
    stdout = _Stream()
    stderr = _Stream()
    monkeypatch.setattr(cli, "sys", SimpleNamespace(platform="win32", stdout=stdout, stderr=stderr))

    cli._configure_windows_stdio()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]
