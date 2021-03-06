import os
import pty
import socket
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing

from madbg.consts import STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO


def enter_pty(attach_as_ctty, connect_output_to_pty=True):
    """
    To be used in a subprocess that want to be run inside a pty.
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


def find_free_port() -> int:
    """ A suggested way of finding a free port on the local machine. Prone to race conditions. """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]
