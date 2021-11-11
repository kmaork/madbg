import os
import pty
import select
import socket
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing

import madbg
from madbg.consts import STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO

JOIN_TIMEOUT = 5


def enter_pty(attach_as_ctty, connect_output_to_pty=True):
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
    for fd_to_override in (STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO) if connect_output_to_pty else (STDIN_FILENO,):
        os.dup2(slave_fd, fd_to_override)
    return master_fd


def run_in_process(func, *args, **kwargs):
    return ProcessPoolExecutor(1).submit(func, *args, **kwargs)


def run_script(script, start_with_ctty, args, kwargs):
    enter_pty(start_with_ctty)
    return script(*args, **kwargs)


def run_script_in_process(script, start_with_ctty, *args, **kwargs):
    return ProcessPoolExecutor(1).submit(run_script, script, start_with_ctty, args, kwargs)


def find_free_port() -> int:
    """ A suggested way of finding a free port on the local machine. Prone to race conditions. """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def run_client(port: int, debugger_input: bytes):
    """ Run client process and return client's tty output """
    master_fd = enter_pty(True)
    os.write(master_fd, debugger_input)
    while True:
        try:
            madbg.client.connect_to_debugger(port=port)
        except ConnectionRefusedError:
            pass
        else:
            break
    os.close(STDOUT_FILENO)
    data = b''
    while select.select([master_fd], [], [], 0)[0]:
        data += os.read(master_fd, 1024)
    return data
