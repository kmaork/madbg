import ctypes
import subprocess
import sys
from threading import Event, Thread, current_thread
from typing import Any, Callable, Dict, Tuple

PR_SET_PTRACER = 0x59616d61
INJECTOR_CODE = 'import sys, hypno; sys.stdin.readline(); hypno.inject_py(int(sys.argv[1]), sys.argv[2])'


class ThreadCommand:
    def __init__(self, func: Callable[[], Any]):
        self.func = func
        self.result = None
        self.success = None
        self.done = Event()

    def execute(self):
        try:
            self.result = self.func()
        except Exception as e:
            self.success = False
            self.result = e
        else:
            self.success = True
        self.done.set()

    def get_result(self):
        # Injection is synchronous, so by now the command should have run
        if not self.done.wait(1):
            raise RuntimeError('Injected code did not run')
        if self.success:
            return self.result
        raise self.result


THREAD_COMMANDS: Dict[Tuple[int, int], ThreadCommand] = {}


def _set_ptracer(pid: int):
    """ Allow the given process to ptrace us when yama's ptrace_scope is 1. Fails silently if yama is disabled. """
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PTRACER, ctypes.c_ulong(pid), 0, 0, 0)


def run_in_thread(thread: Thread, func: Callable[[], Any]):
    """
    Run func in the given thread, even while it is blocked in a syscall, and return its result.
    The frame that thread was running is func's caller's caller's caller (func <- execute <- injected code <- frame).
    """
    if not thread.is_alive():
        raise RuntimeError(f'Given thread is not alive: {thread}')
    key = (current_thread().native_id, thread.native_id)
    command = THREAD_COMMANDS[key] = ThreadCommand(func)
    code = f'__import__("sys").modules[{__name__!r}].THREAD_COMMANDS[{key!r}].execute()'
    try:
        # A process can't ptrace its own threads, so a helper process does the injection
        injector = subprocess.Popen([sys.executable, '-c', INJECTOR_CODE, str(thread.native_id), code],
                                    stdin=subprocess.PIPE)
        _set_ptracer(injector.pid)
        try:
            injector.communicate(b'\n')
        finally:
            _set_ptracer(0)
        if injector.returncode != 0:
            raise RuntimeError(f'Failed injecting code into thread {thread.name}')
        return command.get_result()
    finally:
        del THREAD_COMMANDS[key]
