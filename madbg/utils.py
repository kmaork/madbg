import atexit
import socket
import sys
from collections import defaultdict
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack


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
    sock, _ = server_socket.accept()
    server_socket.close()
    try:
        yield sock.fileno()
    finally:
        sock.close()


def use_context(context_manager, exit_stack=None):
    if exit_stack is None:
        exit_stack = ExitStack()
        atexit.register(exit_stack.close)
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


@contextmanager
def loop_in_thread(func, *args, iteration_after_exit=True, **kwargs):
    cont = True

    def loop():
        while cont:
            func(*args, **kwargs)

    with run_thread(loop) as future:
        try:
            yield future
        finally:
            cont = False
    if iteration_after_exit:
        func(*args, **kwargs)


def opposite_dict(dikt):
    opposite = defaultdict(list)
    for key, value in dikt.items():
        opposite[value].append(key)
    return opposite
