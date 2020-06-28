import os
import time
import madbg
from pytest import mark

from .utils import enter_pty, run_in_process

JOIN_TIMEOUT = 5


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
    master_fd = enter_pty(True)
    os.write(master_fd, debugger_input)
    madbg.client.connect_to_debugger(port=port)


@mark.parametrize('start_debugger_with_ctty', (True, False))
def test_set_trace(port, start_debugger_with_ctty):
    debugger_future = run_in_process(run_set_trace_process, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client_process, port, b'value_to_change += 1\nc\n')
    assert debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)


@mark.parametrize('start_debugger_with_ctty', (True, False))
def test_set_trace_on_connect(port, start_debugger_with_ctty):
    debugger_future = run_in_process(run_set_trace_on_connect_process, start_debugger_with_ctty, port)
    # let the loop run a little
    time.sleep(0.5)
    assert not debugger_future.done()
    client_future = run_in_process(run_client_process, port, b'conti = False\nc\n')
    assert debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)
