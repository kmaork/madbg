import atexit
import socket
import sys
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
