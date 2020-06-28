import select
import socket
import sys
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager

from .communication import receive_message, pipe
from .tty_utils import open_pty, resize_terminal, modify_terminal, set_ctty


class ConnectionCancelled(Exception):
    pass


@contextmanager
def preserve_sys_state():
    sys_argv = sys.argv[:]
    sys_path = sys.path[:]
    try:
        yield
    finally:
        sys.argv = sys_argv
        sys.path = sys_path


@contextmanager
def get_client_connection(ip, port, cancelled_future=None):
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    server_socket.bind((ip, port))
    server_socket.listen(1)
    while not select.select([server_socket], [], [], 0.1)[0]:
        if cancelled_future is not None and cancelled_future.done():
            raise ConnectionCancelled()
    sock, _ = server_socket.accept()
    server_socket.close()
    try:
        yield sock.fileno()
    finally:
        sock.close()


@contextmanager
def remote_pty(ip, port, cancelled_future=None):
    with get_client_connection(ip, port, cancelled_future) as sock:
        # TODO: should we set settings like that, or just write some ansi? https://apple.stackexchange.com/questions/33736/can-a-terminal-window-be-resized-with-a-terminal-command
        term_data = receive_message(sock)
        term_attrs, term_type, term_size = term_data['term_attrs'], term_data['term_type'], term_data['term_size']
        # TODO: what is the correct term type? the pty or the remote tty?
        with open_pty() as (master_fd, slave_fd):
            resize_terminal(slave_fd, term_size[0], term_size[1])
            modify_terminal(slave_fd, term_attrs)
            with set_ctty(slave_fd):
                # TODO: join the thread sometime
                ThreadPoolExecutor(1).submit(pipe, {sock: master_fd, master_fd: sock})
                yield slave_fd, term_type


class Lazy:
    def __init__(self, object_callback):
        self.object_callback = object_callback
        self._object = None
