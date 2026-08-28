import socket

from snoreguard.vrc.handler import VRChatOSCReceiver


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_returns_true_and_stop_releases_port():
    port = _free_port()
    receiver = VRChatOSCReceiver(port, app_instance=None, log_callback=None)
    assert receiver.start() is True
    assert receiver.bind_error is None
    receiver.stop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", port))  # 解放されていれば bind できる


def test_start_returns_false_when_port_in_use():
    port = _free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
        blocker.bind(("127.0.0.1", port))
        receiver = VRChatOSCReceiver(port, app_instance=None, log_callback=None)
        assert receiver.start() is False
        assert receiver.bind_error is not None
        assert receiver.is_running is False
