import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor

from .consts import DEFAULT_IP, DEFAULT_PORT
from .debugger import RemoteIPythonDebugger

DEBUGGER_CONNECTED_SIGNAL = signal.SIGUSR1


def set_trace(ip=DEFAULT_IP, port=DEFAULT_PORT):
    RemoteIPythonDebugger(ip, port).set_trace(sys._getframe(1))


def _wait_for_connection_and_send_signal(ip, port):
    try:
        debugger = RemoteIPythonDebugger(ip, port)
    finally:
        # TODO: on exception, this raises randomly from the main thread and not from set_trace_on_connect
        os.kill(0, DEBUGGER_CONNECTED_SIGNAL)
    return debugger


def set_trace_on_connect(ip=DEFAULT_IP, port=DEFAULT_PORT):
    # TODO: this only works on the main thread :(
    def new_handler(_, frame):
        signal.signal(DEBUGGER_CONNECTED_SIGNAL, old_handler)
        debugger_future.result().set_trace(frame)

    old_handler = signal.signal(DEBUGGER_CONNECTED_SIGNAL, new_handler)
    debugger_future = ThreadPoolExecutor(1).submit(_wait_for_connection_and_send_signal, ip, port)


def post_mortem(ip=DEFAULT_IP, port=DEFAULT_PORT, traceback=None):
    traceback = traceback or sys.exc_info()[2] or sys.last_traceback
    p = RemoteIPythonDebugger(ip, port)
    p.reset()
    p.interaction(None, traceback)


if __name__ == '__main__':
    set_trace(DEFAULT_IP)
