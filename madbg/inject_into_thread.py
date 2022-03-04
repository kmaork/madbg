from types import FrameType
from typing import Callable
import signal
import ctypes
import threading
import inspect

SIGNAL = signal.SIGINT

make_c_handler = ctypes.PYFUNCTYPE(None, ctypes.c_int)
set_c_handler = ctypes.pythonapi.PyOS_setsig


def set_temp_handler(signal: signal.Signals, callback: Callable[[FrameType], None]):
    # TODO: can we use SA_RESETHAND?
    def handler(_signum: int):
        set_c_handler(signal.value, old_handler)
        ctypes.pythonapi.Py_DecRef(ctypes.py_object(handler))
        callback(inspect.currentframe().f_back)

    ctypes.pythonapi.Py_IncRef(ctypes.py_object(handler))
    old_handler = set_c_handler(signal.value, make_c_handler(handler))


def inject_into_thread(thread: threading.Thread, payload: Callable[[FrameType], None]):
    """
    This is not safe. Our handler almost surely has non-reentrant code, which means if the
    target thread is in userspace when the signal is delivered, we might reenter forbidden
    code and crash something or deadlock. This is not extremely likely to happen as the calling thread holds
    the GIL, but of course we need to find a completely safe solution.
    An alternative is to do the same as pydev.debugger did, as mentioned here: https://bugs.python.org/issue35370 -
    either by:
     - pausing all the threads then selectively switching to a thread to make it current and then calling settrace
     - using the new _PyEval_SetTrace API (since python3.9)
     - implementing the settrace ourselves, as done in pydev https://github.com/fabioz/PyDev.Debugger/blob/pydev_debugger_1_9_0/pydevd_attach_to_process/common/py_settrace_37.hpp#L150
    Do we need to send a signal anyway to stop syscalls like sleep and such? Seems that not, according to PEP475.
    Another issue might be collision with an existing signal handler. I'm not sure if it is problematic, as if our handler
    is truly one-shot, and we define it only when we want to inject, then no harm done... But if we ditch the signals
    and use another implementation, this wont be a risk.
    """
    if thread is threading.currentThread():
        payload(inspect.currentframe().f_back)
    else:
        set_temp_handler(SIGNAL, payload)
        signal.pthread_kill(thread.ident, SIGNAL)
