from contextlib import contextmanager
from threading import Event, Thread, current_thread

from pytest import raises

from madbg.threads import run_in_thread


@contextmanager
def running_thread(name: str):
    stop = Event()
    thread = Thread(name=name, target=stop.wait)
    thread.start()
    try:
        yield thread
    finally:
        stop.set()
        thread.join()


def test_run_in_thread():
    with running_thread('target') as thread:
        assert run_in_thread(thread, lambda: current_thread().name) == 'target'


def test_run_in_thread_raises():
    with running_thread('target') as thread:
        with raises(ZeroDivisionError):
            run_in_thread(thread, lambda: 1 / 0)


def test_run_in_dead_thread():
    thread = Thread(target=lambda: None)
    thread.start()
    thread.join()
    with raises(RuntimeError):
        run_in_thread(thread, lambda: None)
