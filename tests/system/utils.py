import os
import pty
import random
from concurrent.futures import ProcessPoolExecutor

STDIN_FILENO = 0
STDOUT_FILENO = 1
STDERR_FILENO = 2


def enter_pty(attach_as_ctty):
    os.setsid()
    master_fd, slave_fd = pty.openpty()
    if attach_as_ctty:
        os.close(os.open(os.ttyname(slave_fd), os.O_RDWR))  # Set the PTY to be our CTTY
    for fd_to_override in (STDIN_FILENO, STDOUT_FILENO, STDERR_FILENO):
        os.dup2(slave_fd, fd_to_override)
    return master_fd


def get_random_port():
    return random.randint(2 ** 10, 2 ** 16)


def run_in_process(func, *args, **kwargs):
    return ProcessPoolExecutor(1).submit(func, *args, **kwargs)
