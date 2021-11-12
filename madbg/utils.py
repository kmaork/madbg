import atexit
import socket
import sys
import threading
from collections import defaultdict
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack

from madbg.tty_utils import print_to_ctty


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
def get_client_connection(ip, port):
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    server_socket.bind((ip, port))
    server_socket.listen(1)
    sock, (client_ip, client_port) = server_socket.accept()
    print_to_ctty(f'Client connected from {client_ip}:{client_port}')
    server_socket.close()
    try:
        yield sock.fileno()
    finally:
        sock.close()


def register_atexit(callback):
    if sys.version_info >= (3, 9):
        # Since python3.9, ThreadPoolExecutor threads are non-daemon, which means they are joined before atexit
        # hooks run - https://bugs.python.org/issue39812
        # Therefore we use threading._register_atexit here because this is used to close such threads.
        threading._register_atexit(callback)
    else:
        atexit.register(callback)


def use_context(context_manager, exit_stack=None):
    if exit_stack is None:
        exit_stack = ExitStack()
        register_atexit(exit_stack.close)
    context_value = exit_stack.enter_context(context_manager)
    return context_value, exit_stack


@contextmanager
def run_thread(func, *args, **kwargs):
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            yield future
        finally:
            future.result()


def opposite_dict(dict_):
    opposite = defaultdict(set)
    for key, value in dict_.items():
        opposite[value].add(key)
    return opposite
