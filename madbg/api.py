import re
import sys
from traceback import format_exc
from inspect import currentframe
from threading import current_thread
from pdb import Restart
from hypno import inject_py
from pyinjector import InjectorError

from .server import DebuggerServer
from .client import connect_to_debugger
from .consts import DEFAULT_ADDR, DEFAULT_CONNECT_TIMEOUT, Addr
from .debugger import RemoteIPythonDebugger


def start(addr: Addr = DEFAULT_ADDR):
    DebuggerServer.make_sure_listening_at(addr)


def _get_debugger(addr: Addr) -> RemoteIPythonDebugger:
    return DebuggerServer.make_sure_listening_at(addr).get_debugger(current_thread())


def _inject_set_trace(pid: int, addr: Addr = DEFAULT_ADDR):
    ip, port = addr
    assert isinstance(ip, str)
    assert re.fullmatch('[.0-9]+', ip)
    assert isinstance(port, int)
    # Do as little as possible while the target is hijacked - anything that raises a signal in the target (e.g. a
    # subprocess exiting while madbg is imported) fails the injection
    try:
        inject_py(pid, f'__import__("threading").Thread(target=lambda: __import__("madbg").start(({ip!r},{port})), '
                       f'name="madbg-start", daemon=True).start()')
    except InjectorError as e:
        # The code was injected, but pyinjector can't unload the injected library under musl
        if 'injector_uninject' not in str(e):
            raise


# TODO: DEFAULT_PORT
# TODO: debugging global should be handled the same way as done_callback
# TODO: add test that would have caught the done callback bug
def attach_to_process(pid: int, port=DEFAULT_ADDR[1], connect_timeout=DEFAULT_CONNECT_TIMEOUT):
    addr = ('127.0.0.1', port)
    _inject_set_trace(pid, addr)
    connect_to_debugger(addr, timeout=connect_timeout)


def set_trace(frame=None, addr: Addr = DEFAULT_ADDR):
    if frame is None:
        frame = currentframe().f_back
    _get_debugger(addr).set_trace(frame)


def post_mortem(traceback=None, addr: Addr = DEFAULT_ADDR):
    traceback = traceback or sys.exc_info()[2] or sys.last_traceback
    _get_debugger(addr).post_mortem(traceback)


def run_with_debugging(python_file, run_as_module=False, argv=(), use_post_mortem=True, use_set_trace=False,
                       addr: Addr = DEFAULT_ADDR, debugger=None):
    full_argv = [python_file, *argv]
    if debugger is None:
        debugger = _get_debugger(addr)
    try:
        debugger.run_py(python_file, run_as_module, full_argv, set_trace=use_set_trace)
    except Restart:
        print("Restarting", python_file, "with arguments:", file=debugger.stdout)
        print("\t" + " ".join(full_argv), file=debugger.stdout)
        return run_with_debugging(python_file, run_as_module=run_as_module, argv=argv,
                                  use_post_mortem=use_post_mortem, use_set_trace=use_set_trace,
                                  addr=addr, debugger=debugger)
    except SystemExit as e:
        print(f"The program exited via sys.exit(). Exit status: {e.code}", end=' ', file=debugger.stdout)
    except SyntaxError:
        raise
    except:
        if use_post_mortem:
            debugger.post_mortem(sys.exc_info()[2], format_exc())
        raise
    else:
        print(f'{python_file} finished running successfully', file=debugger.stdout)


__all__ = ['attach_to_process', 'set_trace', 'start', 'post_mortem', 'run_with_debugging']
