import madbg

from .utils import enter_pty, run_in_process, JOIN_TIMEOUT, run_client


def post_mortem_script(start_with_ctty, port):
    enter_pty(start_with_ctty)
    try:
        1 / 0
    except ZeroDivisionError:
        madbg.post_mortem(port=port)


def test_post_mortem(port, start_debugger_with_ctty):
    debugger_future = run_in_process(post_mortem_script, start_debugger_with_ctty, port)
    assert not debugger_future.done()
    client_future = run_in_process(run_client, port, b'c\n')
    debugger_future.result(JOIN_TIMEOUT)
    client_future.result(JOIN_TIMEOUT)
