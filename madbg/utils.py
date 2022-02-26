import atexit
import sys
import threading
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack


@contextmanager
def preserve_sys_state():
    sys_argv = sys.argv[:]
    sys_path = sys.path[:]
    try:
        yield
    finally:
        sys.argv[:] = sys_argv
        sys.path[:] = sys_path


def register_atexit(callback, *args, **kwargs):
    if sys.version_info >= (3, 9):
        # Since python3.9, ThreadPoolExecutor threads are non-daemon, which means they are joined before atexit
        # hooks run - https://bugs.python.org/issue39812
        threading._register_atexit(callback, *args, **kwargs)
    else:
        atexit.register(callback, *args, **kwargs)


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


class Singleton(type):
    def __init__(cls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cls._INSTANCE = None
        cls._INSTANCE_LOCK = threading.RLock()

    def __call__(cls):
        with cls._INSTANCE_LOCK:
            if cls._INSTANCE is not None:
                return cls._INSTANCE
            instance = super().__call__()
            cls._INSTANCE = instance
        return instance
