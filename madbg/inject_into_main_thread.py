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
    assert prepared
    os.kill(0, SIGNAL)
