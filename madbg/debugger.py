from __future__ import annotations
import runpy
import os
import sys
from bdb import BdbQuit
from contextlib import contextmanager, nullcontext
from typing import ContextManager
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output
from inspect import currentframe
from IPython.terminal.debugger import TerminalPdb
from IPython.terminal.interactiveshell import TerminalInteractiveShell

from .utils import preserve_sys_state, Singleton
from .tty_utils import PTY, TTYConfig, print_to_ctty


class RemoteIPythonDebugger(TerminalPdb, metaclass=Singleton):
    _DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'

    def __init__(self):
        self.pty = PTY.open()
        # A patch until https://github.com/ipython/ipython/issues/11745 is solved
        TerminalInteractiveShell.simple_prompt = False
        self.term_input = Vt100Input(self.pty.slave_reader)
        self.term_output = Vt100_Output.from_pty(self.pty.slave_writer)
        super().__init__(pt_session_options=dict(input=self.term_input, output=self.term_output),
                         stdin=self.pty.slave_reader, stdout=self.pty.slave_writer)
        self.use_rawinput = True
        self.num_clients = 0
        self.done_callback = None
        self.pt_app.key_bindings.remove("c-\\")

    def __del__(self):
        print('Closing connection', file=self.pty.slave_writer, flush=True)
        self.pty.close()

    def notify_client_connect(self, tty_config: TTYConfig):
        self.num_clients += 1
        tty_config.apply(self.pty.slave_fd)
        self.term_output.term = tty_config.term_type

    def notify_client_disconnect(self):
        self.num_clients -= 1
        # TODO: warn if still in trace and last client disconnected

    def preloop(self):
        if self.num_clients == 0:
            print_to_ctty("Waiting for client to connect")

    def trace_dispatch(self, frame, event, arg, check_debugging_global=False):
        """
        Overriding super to allow the check_debugging_global and done_callback args.

        :param check_debugging_global: Whether to start debugging only if _DEBUGGING_GLOBAL is in the globals.
        :param done_callback: a callable to be called when the debug session ends.
        """
        if check_debugging_global:
            if self._DEBUGGING_GLOBAL in frame.f_globals:
                self.set_trace(frame)
            else:
                return None
        bdb_quit = False
        try:
            return super().trace_dispatch(frame, event, arg)
        except BdbQuit:
            bdb_quit = True
        finally:
            if self.quitting or bdb_quit:
                self._on_done()

    def _on_done(self):
        if self.done_callback is not None:
            self.done_callback()
            self.done_callback = None

    def set_trace(self, frame=None, done_callback=None):
        """ Overriding super to add the done_callback argument, allowing cleanup after a debug session """
        if done_callback is not None:
            # set_trace was called again without the previous one exiting -
            # happens on continue -> ctrl-c
            self.done_callback = done_callback
        if frame is None:
            frame = currentframe().f_back
        return super().set_trace(frame)

    def do_continue(self, arg):
        """ Overriding super to add a print """
        if not self.nosigint:
            print('Resuming program, press Ctrl-C to relaunch debugger.', file=self.stdout)
        return super().do_continue(arg)

    do_c = do_cont = do_continue

    def post_mortem(self, traceback):
        self.reset()
        self.interaction(None, traceback)

    def run_py(self, python_file, run_as_module, argv, set_trace=False):
        run_name = '__main__'
        globals = {self._DEBUGGING_GLOBAL: True}
        with preserve_sys_state():
            sys.argv = argv
            if not run_as_module:
                sys.path[0] = os.path.dirname(python_file)
            with self.debug(check_debugging_global=True) if set_trace else nullcontext():
                if run_as_module:
                    runpy.run_module(python_file, alter_sys=True, run_name=run_name, init_globals=globals)
                else:
                    runpy.run_path(python_file, run_name=run_name, init_globals=globals)

    @contextmanager
    def debug(self, check_debugging_global=False) -> ContextManager:
        self.reset()
        sys.settrace(lambda *args: self.trace_dispatch(*args, check_debugging_global=check_debugging_global))
        try:
            yield
        except BdbQuit:
            pass
        finally:
            self.quitting = True
            sys.settrace(None)
