import os
import runpy
import signal
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pdb import Restart
from contextlib import contextmanager

from .consts import DEFAULT_IP, DEFAULT_PORT
from .debugger import RemoteIPythonDebugger

DEBUGGER_CONNECTED_SIGNAL = signal.SIGUSR1


def set_trace(ip=DEFAULT_IP, port=DEFAULT_PORT):
    RemoteIPythonDebugger(ip, port).set_trace(sys._getframe(1))


def _wait_for_connection_and_send_signal(ip, port):
    try:
        debugger = RemoteIPythonDebugger(ip, port)
    finally:
        # TODO: on exception, this raises randomly from the main thread and not from set_trace_on_connect
        os.kill(0, DEBUGGER_CONNECTED_SIGNAL)
    return debugger


def set_trace_on_connect(ip=DEFAULT_IP, port=DEFAULT_PORT):
    # TODO: this only works on the main thread :(
    def new_handler(_, frame):
        signal.signal(DEBUGGER_CONNECTED_SIGNAL, old_handler)
        debugger_future.result().set_trace(frame)

    old_handler = signal.signal(DEBUGGER_CONNECTED_SIGNAL, new_handler)
    debugger_future = ThreadPoolExecutor(1).submit(_wait_for_connection_and_send_signal, ip, port)


def post_mortem(ip=DEFAULT_IP, port=DEFAULT_PORT, traceback=None):
    traceback = traceback or sys.exc_info()[2] or sys.last_traceback
    debugger = RemoteIPythonDebugger(ip, port)
    debugger.post_mortem(traceback)


@contextmanager
def _preserve_sys_state():
    sys_argv = sys.argv[:]
    sys_path = sys.path[:]
    try:
        yield
    finally:
        sys.argv = sys_argv
        sys.path = sys_path


def _run_py(python_file, run_as_module, argv):
    run_name = '__main__'
    with _preserve_sys_state():
        sys.argv = argv
        if not run_as_module:
            sys.path[0] = os.path.dirname(python_file)
        if run_as_module:
            runpy.run_module(python_file, alter_sys=True, run_name=run_name)
        else:
            runpy.run_path(python_file, run_name=run_name)


def run_with_debugging(ip, port, python_file, run_as_module, argv, use_post_mortem=True, use_set_trace=False,
                       debugger=None):
    if debugger is None:
        debugger = RemoteIPythonDebugger(ip, port)
    try:
        if use_set_trace:
            debugger.set_sys_trace()
        _run_py(python_file, run_as_module, argv)
    except Restart:
        print("Restarting", python_file, "with arguments:", file=debugger.stdout)
        print("\t" + " ".join(argv), file=debugger.stdout)
        return run_with_debugging(ip, port, python_file, run_as_module, argv, use_post_mortem, use_set_trace, debugger)
    except SystemExit:
        print("The program exited via sys.exit(). Exit status:", end=' ', file=debugger.stdout)
        print(sys.exc_info()[1], file=debugger.stdout)
    except SyntaxError:
        raise
    except:
        if use_post_mortem:
            print(traceback.format_exc(), file=debugger.stdout)
            print('\nWaiting for debugger connection...', file=debugger.stdout)
            debugger.post_mortem(sys.exc_info()[2])


if __name__ == '__main__':
    set_trace(DEFAULT_IP)

# TODO: update readme with new features, mention similar projects
