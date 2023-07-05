import madbg

from .utils import run_in_process, run_script_in_process, run_client


def post_mortem_script(port):
    try:
        1 / 0
    except ZeroDivisionError:
        madbg.post_mortem(port=port)


def test_post_mortem(port, start_debugger_with_ctty):
    with run_script_in_process(post_mortem_script, start_debugger_with_ctty, port):
        run_in_process(run_client, port, b'c\n').finish()
