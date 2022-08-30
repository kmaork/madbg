from __future__ import annotations
import os
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .debugger import RemoteIPythonDebugger

SIGNAL = signal.SIGUSR2
prepared = False


def prepare_injection(debugger: RemoteIPythonDebugger):
    global prepared
    signal.signal(SIGNAL, lambda _sig, frame: debugger.set_trace(frame))
    prepared = True


def inject():
    """
    The only reason we are using a signal is to inject code to the main thread.
    It doesn't help with ending syscalls because of PEP475, so we could probably just use the add_action api or
    whatever it's called (unless we are in a python version that allows setting trace for other threads).
    But wait, can we use pyinjector to set trace in the other threads??
    """
    assert prepared
    os.kill(0, SIGNAL)
