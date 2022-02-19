import os
import re
import signal
import sys
from select import select
from traceback import format_exc
from contextlib import nullcontext
from inspect import currentframe
from pdb import Restart
from hypno import inject_py
from fcntl import fcntl, F_GETFL, F_SETFL, F_SETOWN
from os import O_ASYNC, getpid

from .client import connect_to_debugger
from .tty_utils import print_to_ctty, set_handler
from .utils import use_context
from .consts import DEFAULT_IP, DEFAULT_PORT, DEFAULT_CONNECT_TIMEOUT
from .debugger import RemoteIPythonDebugger

DEBUGGER_CONNECTED_SIGNAL = signal.SIGUSR1


def _inject_set_trace(pid, ip=DEFAULT_IP, port=DEFAULT_PORT):
    assert isinstance(ip, str)
    assert re.fullmatch('[.0-9]+', ip)
    assert isinstance(port, int)
    sig_num = DEBUGGER_CONNECTED_SIGNAL.value
    inject_py(pid, f'__import__("signal").signal({sig_num},lambda _,f:__import__("madbg").set_trace(f,"{ip}",{port}))')
    os.kill(pid, sig_num)


def attach_to_process(pid: int, port=DEFAULT_PORT, connect_timeout=DEFAULT_CONNECT_TIMEOUT):
    ip = '127.0.0.1'
    _inject_set_trace(pid, ip, port)
    connect_to_debugger(ip, port, timeout=connect_timeout)


def set_trace(frame=None, ip=DEFAULT_IP, port=DEFAULT_PORT):
    if frame is None:
        frame = currentframe().f_back
    debugger, exit_stack = use_context(RemoteIPythonDebugger.connect_and_start(ip, port))
    debugger.set_trace(frame, done_callback=exit_stack.close)


def set_trace_on_connect(ip=DEFAULT_IP, port=DEFAULT_PORT):
    """
    Set up a debugger in another thread, which will signal the main thread when it receives a connection.
    Also set up a signal handler that will call set_trace when the signal is received.
    """
    server_socket, server_exit_stack = use_context(RemoteIPythonDebugger.get_server_socket(ip, port))

    def sigio_handler(signum, frame):
        if select([server_socket], [], [], 0)[0]:
            handler_exit_stack.close()
            sock, _ = server_socket.accept()
            server_exit_stack.close()
            debugger, debugger_exit_stack = use_context(RemoteIPythonDebugger.start_from_new_connection(sock))

            def on_trace_done():
                debugger_exit_stack.close()
                set_trace_on_connect(ip, port)

            debugger.set_trace(frame, done_callback=on_trace_done)
        elif not isinstance(old_handler, signal.Handlers):
            old_handler(signum, frame)

    old_handler, handler_exit_stack = use_context(set_handler(signal.SIGIO, sigio_handler))
    server_fd = server_socket.fileno()
    fcntl(server_fd, F_SETOWN, getpid())
    fcntl(server_fd, F_SETFL, fcntl(server_fd, F_GETFL, 0) | O_ASYNC)
    server_socket.listen(1)
    print_to_ctty(f'Listening for debugger client on {ip}:{port}')


def post_mortem(traceback=None, ip=DEFAULT_IP, port=DEFAULT_PORT):
    traceback = traceback or sys.exc_info()[2] or sys.last_traceback
    with RemoteIPythonDebugger.connect_and_start(ip, port) as debugger:
        debugger.post_mortem(traceback)


def run_with_debugging(python_file, run_as_module=False, argv=(), use_post_mortem=True, use_set_trace=False,
                       ip=DEFAULT_IP, port=DEFAULT_PORT, debugger=None):
    argv = [python_file, *argv]
    with RemoteIPythonDebugger.connect_and_start(ip, port) if debugger is None else nullcontext(debugger) as debugger:
        try:
            debugger.run_py(python_file, run_as_module, argv, set_trace=use_set_trace)
        except Restart:
            print("Restarting", python_file, "with arguments:", file=debugger.stdout)
            print("\t" + " ".join(argv), file=debugger.stdout)
            return run_with_debugging(python_file, run_as_module=run_as_module, argv=argv,
                                      use_post_mortem=use_post_mortem, use_set_trace=use_set_trace,
                                      ip=ip, port=port, debugger=debugger)
        except SystemExit as e:
            print(f"The program exited via sys.exit(). Exit status: {e.code}", end=' ', file=debugger.stdout)
        except SyntaxError:
            raise
        except:
            if use_post_mortem:
                print(format_exc(), file=debugger.stdout)
                debugger.post_mortem(sys.exc_info()[2])
            raise
        else:
            print(f'{python_file} finished running successfully', file=debugger.stdout)


__all__ = ['attach_to_process', 'set_trace', 'set_trace_on_connect', 'post_mortem', 'run_with_debugging']
