import madbg
from pytest import raises

from madbg.debugger import RemoteIPythonDebugger

from .utils import run_in_process, run_script_in_process, run_client


def set_trace_script(port, times=1, debugger_fails=False):
    if debugger_fails:
        RemoteIPythonDebugger.__init__ = lambda *a, **k: 1 / 0
    for _ in range(times):
        madbg.set_trace(port=port)


def set_trace_and_expect_var_to_change_script(port) -> bool:
    """
    Set two vars to the same value, start the debugger, and return True if one of the vars has changed.
    """
    original_value = value_to_change = 0
    madbg.set_trace(port=port)
    return original_value != value_to_change


def test_set_trace(port, start_debugger_with_ctty):
    with run_script_in_process(set_trace_and_expect_var_to_change_script, start_debugger_with_ctty, port):
        assert b'Closing connection' in run_in_process(run_client, port, b'value_to_change += 1\nc\n').finish().get(0)


def test_set_trace_and_connect_twice(port, start_debugger_with_ctty):
    with run_script_in_process(set_trace_script, start_debugger_with_ctty, port, 2):
        assert b'Closing connection' in run_in_process(run_client, port, b'q\n').finish().get(0)
        assert b'Closing connection' in run_in_process(run_client, port, b'q\n').finish().get(0)


def test_set_trace_twice_and_continue(port, start_debugger_with_ctty):
    with run_script_in_process(set_trace_script, start_debugger_with_ctty, port, 2):
        assert b'Closing connection' in run_in_process(run_client, port, b'c\nq\n').finish().get(0)


def test_set_trace_and_quit_debugger(port, start_debugger_with_ctty):
    with run_script_in_process(set_trace_script, start_debugger_with_ctty, port):
        run_in_process(run_client, port, b'q\n').finish()


def test_set_trace_with_failing_debugger(port, start_debugger_with_ctty, monkeypatch):
    with raises(ZeroDivisionError):
        with run_script_in_process(set_trace_script, start_debugger_with_ctty, port, debugger_fails=True) as script_result:
            assert ZeroDivisionError.__name__.encode() in run_in_process(run_client, port, b'bla\n').finish().get(0)
