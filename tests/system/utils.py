import os
import pty
import select
import socket
import multiprocessing as mp
from contextlib import closing, _GeneratorContextManager
from functools import wraps
from pathlib import Path

from madbg import client
from madbg.consts import STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO
from madbg.tty_utils import PTY

JOIN_TIMEOUT = 10
CONNECT_TIMEOUT = 5
SCRIPTS_PATH = Path(__file__).parent / 'scripts'

# forked subprocesses don't run exitfuncs
mp_context = mp.get_context("spawn")


class FinishableGeneratorContextManager(_GeneratorContextManager):
    def finish(self):
        with self as result:
            return result


def finishable_contextmanager(func):
    @wraps(func)
    def helper(*args, **kwds):
        return FinishableGeneratorContextManager(func, args, kwds)
    return helper


@finishable_contextmanager
def run_in_process(func, *args, **kwargs):
    pool = mp_context.Pool(1)
    apply_result = pool.apply_async(func, args, kwargs)
    pool.close()
    try:
        yield apply_result
    except:
        pool.terminate()
        raise
    else:
        # Wait for the result and raise an error if failed
        apply_result.get(JOIN_TIMEOUT)
        pool.join()


def _run_script(script, start_with_ctty, args, kwargs):
    """
    Meant to be called inside a python subprocess, do NOT call directly.
    """
    enter_pty(start_with_ctty)
    return script(*args, **kwargs)


def run_script_in_process(script, start_with_ctty, *args, **kwargs):
    return run_in_process(_run_script, script, start_with_ctty, args, kwargs)


def find_free_port() -> int:
    """ A suggested way of finding a free port on the local machine. Prone to race conditions. """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def enter_pty(attach_as_ctty, connect_stdio_to_pty=True):
    """
    To be used in a subprocess that wants to be run inside a pty.
    Enters a new session, opens a new pty and sets the pty to be its controlling tty.
    If connect_output_to_pty is True, the process's stdio will be redirected to the pty's
    slave interface.

    :return: The master fd for the pty.
    """
    os.setsid()
    master_fd, slave_fd = pty.openpty()
    if attach_as_ctty:
        os.close(os.open(os.ttyname(slave_fd), os.O_RDWR))  # Set the PTY to be our CTTY
    if connect_stdio_to_pty:
        for fd_to_override in (STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO):
            os.dup2(slave_fd, fd_to_override)
    return master_fd, slave_fd


def run_client(port: int, debugger_input: bytes):
    """ Run client process and return client's tty output """
    master_fd, slave_fd = enter_pty(True, connect_stdio_to_pty=False)
    os.write(master_fd, debugger_input)
    client.connect_to_debugger(port=port, timeout=CONNECT_TIMEOUT, in_fd=slave_fd, out_fd=slave_fd)
    data = b''
    while select.select([master_fd], [], [], 0)[0]:
        data += os.read(master_fd, 4096)
    PTY(master_fd, slave_fd).close()
    return data
