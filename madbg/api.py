import os
import re
import signal
import sys
from traceback import format_exc
from contextlib import nullcontext
from inspect import currentframe
from pdb import Restart
from hypno import inject_py

from .server import DebuggerServer
from .client import connect_to_debugger
from .consts import DEFAULT_ADDR, DEFAULT_CONNECT_TIMEOUT, Addr
from .debugger import RemoteIPythonDebugger

DEBUGGER_CONNECTED_SIGNAL = signal.SIGUSR1


def start(addr: Addr = DEFAULT_ADDR):
    DebuggerServer.make_sure_listening_at(addr)


def _inject_set_trace(pid: int, addr: Addr = DEFAULT_ADDR):
    assert isinstance(ip, str)
    assert re.fullmatch('[.0-9]+', ip)
    assert isinstance(port, int)
    sig_num = DEBUGGER_CONNECTED_SIGNAL.value
    inject_py(pid, f'__import__("signal").signal({sig_num},lambda _,f:__import__("madbg").set_trace(f,"{ip}",{port}))')
    os.kill(pid, sig_num)


# TODO: DEFAULT_PORT
def attach_to_process(pid: int, port=DEFAULT_ADDR[1], connect_timeout=DEFAULT_CONNECT_TIMEOUT):
    addr = ('127.0.0.1', port)
    _inject_set_trace(pid, addr)
    connect_to_debugger(addr, timeout=connect_timeout)


def set_trace(frame=None, addr: Addr = DEFAULT_ADDR):
    if frame is None:
        frame = currentframe().f_back
    start(addr)
    RemoteIPythonDebugger().set_trace(frame)


def post_mortem(traceback=None, addr: Addr = DEFAULT_ADDR):
    start(addr)
    traceback = traceback or sys.exc_info()[2] or sys.last_traceback
    RemoteIPythonDebugger().post_mortem(traceback)


def run_with_debugging(python_file, run_as_module=False, argv=(), use_post_mortem=True, use_set_trace=False,
                       addr: Addr = DEFAULT_ADDR, debugger=None):
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


__all__ = ['attach_to_process', 'set_trace', 'start', 'post_mortem', 'run_with_debugging']
