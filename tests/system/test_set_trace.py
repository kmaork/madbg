import madbg
from unittest.mock import Mock
from pytest import raises

from madbg.debugger import RemoteIPythonDebugger

from .utils import run_in_process, run_script_in_process, JOIN_TIMEOUT, run_client


def set_trace_script(port):
    madbg.set_trace(port=port)


def set_trace_and_expect_var_to_change_script(port) -> bool:
    """
    Set two vars to the same value, start the debugger, and return True if one of the vars has changed.
    """
    original_value = value_to_change = 0
    madbg.set_trace(port=port)
    return original_value != value_to_change


def test_set_trace(port, start_debugger_with_ctty):
    debugger_future = run_script_in_process(set_trace_and_expect_var_to_change_script, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client, port, b'value_to_change += 1\nc\n')
    assert debugger_future.result(JOIN_TIMEOUT)
    client_output = client_future.result(JOIN_TIMEOUT)
    assert b'Closing connection' in client_output


def test_set_trace_and_quit_debugger(port, start_debugger_with_ctty):
    debugger_future = run_script_in_process(set_trace_script, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client, port, b'q\n')
    debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)


def test_set_trace_with_failing_debugger(port, start_debugger_with_ctty, monkeypatch):
    monkeypatch.setattr(RemoteIPythonDebugger, '__init__', Mock(side_effect=lambda *a, **k: 1 / 0))
    debugger_future = run_script_in_process(set_trace_script, start_debugger_with_ctty, port)
    client_future = run_in_process(run_client, port, b'bla\n')
    with raises(ZeroDivisionError):
        debugger_future.result(JOIN_TIMEOUT)
    client_output = client_future.result(JOIN_TIMEOUT)
    assert ZeroDivisionError.__name__.encode() in client_output
