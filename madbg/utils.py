import sys
from threading import RLock
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@contextmanager
def preserve_sys_state():
    sys_argv = sys.argv[:]
    sys_path = sys.path[:]
    try:
        yield
    finally:
        sys.argv[:] = sys_argv
        sys.path[:] = sys_path


class Handlers:
    def __init__(self):
        self.keys_to_funcs = {}

    def register(self, key):
        def decorator(func):
            self.keys_to_funcs[key] = func
            return func

        return decorator

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return BoundHandlers(self, instance, owner)


@dataclass
class BoundHandlers:
    handlers: Handlers
    instance: Any
    owner: Any

    def __call__(self, key):
        self.handlers.keys_to_funcs[key](self.instance, key)

    def __iter__(self):
        return ((key, func.__get__(self.instance, self.owner)) for key, func in self.handlers.keys_to_funcs.items())


class Locked:
    def __init__(self, value: Any, lock: RLock = None):
        if lock is None:
            lock = RLock()
        self._value = value
        self._lock = lock

    def set(self, new_val: Any):
        with self:
            self._value = new_val

    # TODO: make generic
    def __enter__(self):
        self._lock.acquire()
        return self._value

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()
