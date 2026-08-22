import queue
import threading

import numpy as np
import pytest

import snoreguard.audio_service as audio_service_module
from core.settings import RuleSettings
from snoreguard.audio_service import AudioService


class _FakeStream:
    """読み取りで例外を投げる sd.InputStream の代替"""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, frames):
        raise RuntimeError("PortAudio device lost")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(audio_service_module.sd, "InputStream", _FakeStream)
    monkeypatch.setattr(
        audio_service_module.sd,
        "query_devices",
        lambda: [{"name": "fake", "max_input_channels": 1}],
    )
    stopped = []
    done = threading.Event()

    def on_stopped(error):
        stopped.append(error)
        done.set()

    svc = AudioService(
        RuleSettings(),
        queue.Queue(maxsize=5),
        snore_detected_callback=lambda: None,
        log_callback=lambda msg, level="info": None,
        on_stream_stopped=on_stopped,
    )
    return svc, stopped, done


def test_stream_error_is_reported_via_callback(service):
    svc, stopped, done = service
    svc.start(0)
    assert done.wait(timeout=5)
    assert stopped and "device lost" in stopped[0]
    assert svc.is_running is False
    assert "device lost" in (svc.last_error or "")


def test_normal_stop_reports_none(monkeypatch):
    class _OkStream(_FakeStream):
        def read(self, frames):
            return np.zeros((frames, 1), dtype=np.float32), False

    monkeypatch.setattr(audio_service_module.sd, "InputStream", _OkStream)
    monkeypatch.setattr(
        audio_service_module.sd,
        "query_devices",
        lambda: [{"name": "fake", "max_input_channels": 1}],
    )
    stopped = []
    done = threading.Event()
    svc = AudioService(
        RuleSettings(),
        queue.Queue(maxsize=5),
        snore_detected_callback=lambda: None,
        log_callback=lambda msg, level="info": None,
        on_stream_stopped=lambda e: (stopped.append(e), done.set()),
    )
    svc.start(0)
    svc.stop()
    assert done.wait(timeout=5)
    assert stopped == [None]
