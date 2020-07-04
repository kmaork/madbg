import os
import socket
from functools import partial
from tty import setraw
import atexit
import termios
from contextlib import contextmanager

from .communication import pipe_until_closed, send_message
from .consts import DEFAULT_IP, DEFAULT_PORT


def get_tty_handle():
    return os.open(os.ctermid(), os.O_RDWR)


# TODO: if server fails to die, we have no control of the local terminal :(
# TODO: support windows?
# TODO: use gdb or ptrace to attach to process
@contextmanager
def tmp_atexit(func, *args, **kwargs):
    atexit.register(func, *args, **kwargs)
    try:
        yield
    finally:
        atexit.unregister(func)


@contextmanager
def promise_cleanup(func, cleanup):
    with tmp_atexit(cleanup):
        try:
            yield func()
        finally:
            cleanup()


def prepare_terminal():
    tty_handle = get_tty_handle()
    old_tty_mode = termios.tcgetattr(tty_handle)
    set_raw = partial(setraw, tty_handle, termios.TCSANOW)
    cleanup = partial(termios.tcsetattr, tty_handle, termios.TCSANOW, old_tty_mode)
    # TODO: save a backup of the terminal setting to the disk, providing an entry point to restore them
    return promise_cleanup(set_raw, cleanup)


@contextmanager
def connect_to_server(ip, port):
    s = socket.socket()
    s.connect((ip, port))
    try:
        yield s
    finally:
        s.close()


def connect_to_debugger(ip=DEFAULT_IP, port=DEFAULT_PORT):
    # TODO: allow passing timeout (that can be infinite)
    with connect_to_server(ip, port) as socket:
        tty_handle = get_tty_handle()
        term_size = os.get_terminal_size(tty_handle)
        term_data = dict(term_attrs=termios.tcgetattr(tty_handle),
                         # prompt toolkit will receive this string, and it can be 'unknown'
                         term_type=os.environ.get("TERM", "unknown"),
                         term_size=(term_size.lines, term_size.columns))
        send_message(socket, term_data)
        with prepare_terminal():
            socket_fd = socket.fileno()
            pipe_until_closed({0: socket_fd, socket_fd: 1})  # TODO: use the terminal directly instead of 0 and 1?


"""
ipdb<->pty(slave<->master)<->socket<->client<->tty
"""
