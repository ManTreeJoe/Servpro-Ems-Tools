"""Select a loopback port outside browser-blocked well-known service ports."""
import socket


def available_port():
    # Do not use pywebview's random low ports (e.g. 4045 is blocked by Edge).
    # Probe rather than terminating a process that already owns a port.
    for port in range(53100, 53200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise RuntimeError('No free OneLoss DEV port in 53100–53199. Close an unused DEV instance and retry.')
