import threading
import signal

from .inject_into_thread import inject_into_thread, SIGNAL
from .api import set_trace


def choose_thread() -> threading.Thread:
    threads = threading.enumerate()
    for i, thread in enumerate(threads):
        print(f'{i + 1}. {thread.name}')
    thread_i = int(input('Choose: ')) - 1
    return threads[thread_i]


def demo():
    signal.signal(SIGNAL, lambda *a: print('Good!'))
    thread = choose_thread()
    inject_into_thread(thread, set_trace)
