import os
import signal

from .debugger import RemoteIPythonDebugger

SIGNAL = signal.SIGUSR2


def prepare_injection():
    def iRemoteIPythonDebugger():
        signal.signal(SIGNAL, signal.SIG_IGN)
        return RemoteIPythonDebugger()
    signal.signal(SIGNAL, lambda _sig, frame: iRemoteIPythonDebugger().set_trace(frame))


def inject():
    os.kill(0, SIGNAL)
