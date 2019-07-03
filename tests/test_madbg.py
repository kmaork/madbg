import os
from pytest import mark
import madbg
import madbg.api
import madbg.client

from .utils import enter_pty, get_random_port, run_in_process

JOIN_TIMEOUT = 3


def run_set_trace_process(start_with_ctty, port):
    """
    Set two vars to the same value, start the debugger, and return True if one of the vars has changed.
    """
    enter_pty(start_with_ctty)
    original_value = value_to_change = 0
    madbg.api.set_trace(port=port)
    return original_value != value_to_change


def run_client_process(port):
    master_fd = enter_pty(True)
    os.write(master_fd, 'value_to_change += 1\nc\n'.encode())
    madbg.client.debug(port=port)


@mark.parametrize('start_debugger_with_ctty', (True, False))
def test_set_trace(start_debugger_with_ctty):
    # TODO: test more edge cases and ipdb commands
    port = get_random_port()
    debugger_future = run_in_process(run_set_trace_process, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client_process, port)
    assert debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)
