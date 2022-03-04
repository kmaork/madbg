import os
import pickle
import socket
import struct
import time
import atexit
from functools import partial
from tty import setraw
from termios import tcgetattr, tcsetattr, TCSANOW
from contextlib import contextmanager

from .communication import Piping
from .consts import DEFAULT_ADDR, STDIN_FILENO, STDOUT_FILENO, DEFAULT_CONNECT_TIMEOUT, MESSAGE_LENGTH_FMT
from .tty_utils import TTYConfig


def get_tty_handle():
    # TODO: shouldn't this actually be stdout?
    return os.open(os.ctermid(), os.O_RDWR)


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
    old_tty_mode = tcgetattr(tty_handle)
    set_raw = partial(setraw, tty_handle, TCSANOW)
    cleanup = partial(tcsetattr, tty_handle, TCSANOW, old_tty_mode)
    return promise_cleanup(set_raw, cleanup)


@contextmanager
def connect_to_server(ip, port, timeout):
    original_timeout = timeout
    start_time = time.time()
    s = None
    while not s:
        try:
            s = socket.create_connection((ip, port), timeout=timeout)
        except ConnectionRefusedError:
            pass
        timeout = original_timeout - (time.time() - start_time)
        if timeout <= 0:
            raise TimeoutError()
    try:
        yield s
    finally:
        s.close()


def connect_to_debugger(addr=DEFAULT_ADDR, timeout=DEFAULT_CONNECT_TIMEOUT,
                        in_fd=STDIN_FILENO, out_fd=STDOUT_FILENO):
    # TODO: use asyncio, and parse addr correctly
    with connect_to_server(*addr, timeout) as socket:
        tty_handle = get_tty_handle()
        message = pickle.dumps(TTYConfig.get(tty_handle))
        message_len = struct.pack(MESSAGE_LENGTH_FMT, len(message))
        socket.sendall(message_len)
        socket.sendall(message)

        with prepare_terminal():
            socket_fd = socket.fileno()
            Piping({in_fd: {socket_fd}, socket_fd: {out_fd}}).run()
