import time
import madbg

from .utils import run_in_process, run_script_in_process, run_client


def set_trace_on_connect_script(port) -> bool:
    """
    Enter an infinite loop and break it using set_trace_on_connect.
    """
    madbg.set_trace_on_connect(port=port)
    conti = True
    while conti:
        time.sleep(0.1)
    return True


def test_set_trace_on_connect(port, start_debugger_with_ctty):
    with run_script_in_process(set_trace_on_connect_script, start_debugger_with_ctty, port) as script_result:
        # Test we can connect twice
        run_in_process(run_client, port, b'q\n').finish()
        run_in_process(run_client, port, b'conti = False\nc\n').finish()
    assert script_result.get(0)


def test_set_trace_on_connect_can_exit(port, start_debugger_with_ctty):
    run_script_in_process(madbg.set_trace_on_connect, start_debugger_with_ctty, port=port).finish()
