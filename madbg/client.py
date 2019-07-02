import os
import socket
from functools import partial
from tty import setraw
import atexit
import termios
from contextlib import contextmanager

from .communication import pipe, send_message
from .consts import DEFAULT_PORT

TTY_HANDLE = 0  # todo: what should this really be?


# todo: if server fails to die, we have no control of the local terminal :(
# todo: support windows in client?
# todo: allow connecting asynchronously to server

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
    old_tty_mode = termios.tcgetattr(TTY_HANDLE)
    set_raw = partial(setraw, TTY_HANDLE, termios.TCSANOW)
    cleanup = partial(termios.tcsetattr, TTY_HANDLE, termios.TCSANOW, old_tty_mode)
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


def debug(ip='127.0.0.1', port=DEFAULT_PORT):
    with connect_to_server(ip, port) as socket:
        term_size = os.get_terminal_size(TTY_HANDLE)
        term_data = dict(term_attrs=termios.tcgetattr(TTY_HANDLE),
                         # prompt toolkit will receive this string, and it can be 'unknown'
                         term_type=os.environ.get("TERM", "unknown"),
                         term_size=(term_size.lines, term_size.columns))
        send_message(socket, term_data)
        with prepare_terminal():
            socket_fd = socket.fileno()
            pipe({0: socket_fd, socket_fd: 1})  # TODO: use the terminal directly instead of 0 and 1?


"""
ipdb<->pty(slave<->master)<->socket<->client<->tty
"""
