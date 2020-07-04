import os
import select
import time
import madbg
from unittest.mock import Mock
from pytest import raises
from madbg.debugger import RemoteIPythonDebugger

from .utils import enter_pty, run_in_process

JOIN_TIMEOUT = 10


def run_set_trace_process(start_with_ctty, port) -> bool:
    """
    Set two vars to the same value, start the debugger, and return True if one of the vars has changed.
    """
    enter_pty(start_with_ctty)
    original_value = value_to_change = 0
    madbg.set_trace(port=port)
    return original_value != value_to_change


def run_set_trace_on_connect_process(start_with_ctty, port) -> bool:
    """
    Enter an infinite loop and break it using set_trace_on_connect.
    """
    enter_pty(start_with_ctty)
    madbg.set_trace_on_connect(port=port)
    conti = True
    while conti:
        time.sleep(0.1)
    return True


def run_client_process(port: int, debugger_input: bytes):
    """ Run client process and return client's tty output """
    master_fd = enter_pty(True)
    os.write(master_fd, debugger_input)
    while True:
        try:
            madbg.client.connect_to_debugger(port=port)
        except ConnectionRefusedError:
            pass
        else:
            break
    data = b''
    while select.select([master_fd], [], [], 0)[0]:
        data += os.read(master_fd, 1024)
    return data



def test_set_trace(port, start_debugger_with_ctty):
    debugger_future = run_in_process(run_set_trace_process, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client_process, port, b'value_to_change += 1\nc\n')
    assert debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)


def test_set_trace_with_failing_debugger(port, start_debugger_with_ctty, monkeypatch):
    monkeypatch.setattr(RemoteIPythonDebugger, '__init__', Mock(side_effect=lambda *a, **k: 1 / 0))
    debugger_future = run_in_process(run_set_trace_process, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client_process, port, b'value_to_change += 1\nc\n')
    with raises(ZeroDivisionError):
        debugger_future.result(JOIN_TIMEOUT)
    assert ZeroDivisionError.__name__.encode() in client_future.result(JOIN_TIMEOUT)


def test_set_trace_on_connect(port, start_debugger_with_ctty):
    debugger_future = run_in_process(run_set_trace_on_connect_process, start_debugger_with_ctty, port)
    # let the loop run a little
    time.sleep(0.5)
    assert not debugger_future.done()
    client_future = run_in_process(run_client_process, port, b'conti = False\nc\n')
    assert debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)
