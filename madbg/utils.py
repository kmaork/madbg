import sys
import threading
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
