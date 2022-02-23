import atexit
import sys
import threading
from collections import defaultdict
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from typing import Dict, Any, Set


@contextmanager
def preserve_sys_state():
    sys_argv = sys.argv[:]
    sys_path = sys.path[:]
    try:
        yield
    finally:
        sys.argv = sys_argv
        sys.path = sys_path


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


def opposite_dict(dict_: Dict[Any, Set[Any]]) -> Dict[Any, Set[Any]]:
    opposite = defaultdict(set)
    for key, values in dict_.items():
        for value in values:
            opposite[value].add(key)
    return opposite
