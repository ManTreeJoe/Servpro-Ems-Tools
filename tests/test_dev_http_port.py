import socket
from dev_http_port import available_port


def test_available_port_is_safe_and_skips_busy_port():
    first = available_port()
    assert 53100 <= first < 53200
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(('127.0.0.1', first))
        occupied.listen()
        second = available_port()
        assert 53100 <= second < 53200
        assert second != first
