import sys
import types

from snoreguard import notify


def test_beep_is_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    notify.beep()  # 例外が出ないこと


def test_beep_calls_winsound_in_background_on_windows(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(Beep=lambda f, d: calls.append((f, d)))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    thread = notify.beep(880, 50)
    assert thread is not None
    thread.join(timeout=2)
    assert calls == [(880, 50)]


def test_beep_swallows_winsound_errors(monkeypatch):
    def boom(f, d):
        raise RuntimeError("no sound device")

    monkeypatch.setitem(sys.modules, "winsound", types.SimpleNamespace(Beep=boom))
    monkeypatch.setattr(sys, "platform", "win32")
    thread = notify.beep()
    thread.join(timeout=2)  # 例外はスレッド内で握られ、ここには伝播しない
    assert not thread.is_alive()
