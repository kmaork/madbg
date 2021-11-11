import time
from pytest import raises
from madbg import run_with_debugging

from .utils import run_script_in_process, JOIN_TIMEOUT, SCRIPTS_PATH, run_in_process, run_client


def run_with_debugging_script(port):
    run_with_debugging(str(SCRIPTS_PATH / 'divide_with_zero.py'), port=port)


def test_run_with_debugging(port, start_debugger_with_ctty):
    debugger_future = run_script_in_process(run_with_debugging_script, start_debugger_with_ctty, port)
    time.sleep(3)
    assert not debugger_future.done()
    client_future = run_in_process(run_client, port, b'c\n')
    with raises(ZeroDivisionError):
        debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)
