import time
import madbg

from .utils import enter_pty, run_in_process, JOIN_TIMEOUT, run_client


def set_trace_on_connect_script(start_with_ctty, port) -> bool:
    """
    Enter an infinite loop and break it using set_trace_on_connect.
    """
    enter_pty(start_with_ctty)
    madbg.set_trace_on_connect(port=port)
    conti = True
    while conti:
        time.sleep(0.1)
    return True


def test_set_trace_on_connect(port, start_debugger_with_ctty):
    debugger_future = run_in_process(set_trace_on_connect_script, start_debugger_with_ctty, port)
    # let the loop run a little
    time.sleep(0.5)
    assert not debugger_future.done()
    client_future = run_in_process(run_client, port, b'conti = False\nc\n')
    assert debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)
