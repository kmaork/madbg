import os
import runpy
import signal
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pdb import Restart
from contextlib import contextmanager
from threading import Event

from .consts import DEFAULT_IP, DEFAULT_PORT
from .debugger import RemoteIPythonDebugger, ConnectionCancelled
from .utils import LazyInit

DEBUGGER_CONNECTED_SIGNAL = signal.SIGUSR1


def set_trace(ip=DEFAULT_IP, port=DEFAULT_PORT):
    RemoteIPythonDebugger(ip, port).set_trace(sys._getframe(1))


def _wait_for_connection_and_send_signal(ip, port, signal_handler_ready):
    signal_handler_ready.wait()
    try:
        debugger = RemoteIPythonDebugger(ip, port)
        LazyInit.initialize_lazy_object(debugger)
        os.kill(0, DEBUGGER_CONNECTED_SIGNAL)
        return debugger
    except:
        # Invoke the signal handler that will try to fetch this future's result and raise this exception
        os.kill(0, DEBUGGER_CONNECTED_SIGNAL)
        raise


def set_trace_on_connect(ip=DEFAULT_IP, port=DEFAULT_PORT):
    """
    Set up a debugger in another thread, which will signal the main thread when it receives a connection.
    Also set up a signal handler that will call set_trace when the signal is received.
    """

    # TODO: the threading causes errors with the ipython history sqlite db.
    # TODO: this only works on the main thread :(
    # TODO: allow cancelling that

    def new_handler(_, frame):
        signal.signal(DEBUGGER_CONNECTED_SIGNAL, old_handler)
        try:
            debugger = debugger_future.result()
        except ConnectionCancelled:
            pass
        else:
            debugger.on_shutdown.add_done_callback(lambda _: set_trace_on_connect(ip, port))
            debugger.set_trace(frame)

    signal_handler_ready = Event()
    debugger_future = ThreadPoolExecutor(1).submit(_wait_for_connection_and_send_signal, ip, port, signal_handler_ready)
    old_handler = signal.signal(DEBUGGER_CONNECTED_SIGNAL, new_handler)
    signal_handler_ready.set()


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
    # TODO: check and test this behavior
    # TODO: add option for set_trace_on_connect (would have to make the debugger a thread safe singleton, and allow cancelling set_trace_on_connect)
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
            debugger.post_mortem(sys.exc_info()[2])
    else:
        print('{} finished running successfully', file=debugger.stdout)


if __name__ == '__main__':
    set_trace(DEFAULT_IP)

# TODO: update readme with new features, mention similar projects
