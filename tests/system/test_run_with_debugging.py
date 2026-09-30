from pytest import raises
from madbg import run_with_debugging

from .utils import run_script_in_process, SCRIPTS_PATH, run_in_process, run_client


def run_divide_with_zero_with_debugging_script(port, post_mortem, set_trace):
    run_with_debugging(str(SCRIPTS_PATH / 'divide_with_zero.py'), port=port, use_post_mortem=post_mortem,
                       use_set_trace=set_trace)


def test_run_with_debugging_with_post_mortem(port, start_debugger_with_ctty):
    with raises(ZeroDivisionError):
        with run_script_in_process(run_divide_with_zero_with_debugging_script, start_debugger_with_ctty, port,
                                   set_trace=False, post_mortem=True):
            run_in_process(run_client, port, b'c\n').finish()


def test_run_with_debugging_with_set_trace(port, start_debugger_with_ctty):
    with run_script_in_process(run_divide_with_zero_with_debugging_script, start_debugger_with_ctty, port,
                                            set_trace=True, post_mortem=False):
        run_in_process(run_client, port, b'n\nn\nyo = 0\nc\n').finish()
