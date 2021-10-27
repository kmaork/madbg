import os
import re
import signal
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pdb import Restart
from hypno import inject_py

from .client import connect_to_debugger
from .utils import use_context
from .consts import DEFAULT_IP, DEFAULT_PORT
from .debugger import RemoteIPythonDebugger

DEBUGGER_CONNECTED_SIGNAL = signal.SIGUSR1


def _inject_set_trace(pid, ip=DEFAULT_IP, port=DEFAULT_PORT):
    assert isinstance(ip, str)
    assert re.fullmatch('[.0-9]+', ip)
    assert isinstance(port, int)
    sig_num = DEBUGGER_CONNECTED_SIGNAL.value
    inject_py(pid, f'__import__("signal").signal({sig_num},lambda _,f:__import__("madbg").set_trace("{ip}",{port},f))')
    os.kill(pid, sig_num)


def attach_to_process(pid: int, port=DEFAULT_PORT, connect_timeout=5):
    ip = '127.0.0.1'
    _inject_set_trace(pid, ip, port)
    connect_to_debugger(ip, port, timeout=connect_timeout)


def set_trace(ip=DEFAULT_IP, port=DEFAULT_PORT, frame=None):
    if frame is None:
        frame = sys._getframe(1)
    RemoteIPythonDebugger.connect_and_set_trace(ip, port, frame)


def _wait_for_connection_and_send_signal(ip, port):
    try:
        sock, exit_stack = use_context(RemoteIPythonDebugger.connect(ip, port))
        return sock, exit_stack
    finally:
        # Invoke the signal handler that will try to fetch this future's result and raise this exception
        os.kill(0, DEBUGGER_CONNECTED_SIGNAL)


def set_trace_on_connect(ip=DEFAULT_IP, port=DEFAULT_PORT):
    """
    Set up a debugger in another thread, which will signal the main thread when it receives a connection.
    Also set up a signal handler that will call set_trace when the signal is received.
    """

    def new_handler(_, frame):
        signal.signal(DEBUGGER_CONNECTED_SIGNAL, old_handler)
        sock, exit_stack = debugger_future.result()

        def on_trace_done():
            exit_stack.close()
            set_trace_on_connect(ip, port)

        debugger, _ = use_context(RemoteIPythonDebugger.start(sock), exit_stack)
        debugger.set_trace(frame, done_callback=lambda: on_trace_done)

    old_handler = signal.signal(DEBUGGER_CONNECTED_SIGNAL, new_handler)
    debugger_future = ThreadPoolExecutor(1).submit(_wait_for_connection_and_send_signal, ip, port)


def post_mortem(ip=DEFAULT_IP, port=DEFAULT_PORT, traceback=None):
    traceback = traceback or sys.exc_info()[2] or sys.last_traceback
    with RemoteIPythonDebugger.connect_and_start(ip, port) as debugger:
        debugger.post_mortem(traceback)


def run_with_debugging(ip, port, python_file, run_as_module, argv, use_post_mortem=True, use_set_trace=False,
                       debugger=None):
    with RemoteIPythonDebugger.connect_and_start(ip, port) if debugger is None else nullcontext(debugger) as debugger:
        try:
            debugger.run_py(python_file, run_as_module, argv, set_trace=use_set_trace)
        except Restart:
            print("Restarting", python_file, "with arguments:", file=debugger.stdout)
            print("\t" + " ".join(argv), file=debugger.stdout)
            return run_with_debugging(ip, port, python_file, run_as_module, argv, use_post_mortem, use_set_trace,
                                      debugger)
        except SystemExit as e:
            print(f"The program exited via sys.exit(). Exit status: {e.code}", end=' ', file=debugger.stdout)
        except SyntaxError:
            raise
        except:
            if use_post_mortem:
                print(traceback.format_exc(), file=debugger.stdout)
                debugger.post_mortem(sys.exc_info()[2])
            else:
                raise
        else:
            print(f'{python_file} finished running successfully', file=debugger.stdout)


__all__ = ['attach_to_process', 'set_trace', 'set_trace_on_connect', 'post_mortem', 'run_with_debugging']
