from __future__ import annotations
import runpy
import os
import sys
from bdb import BdbQuit
from contextlib import contextmanager, nullcontext
from typing import ContextManager
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output
from IPython.terminal.debugger import TerminalPdb
from IPython.terminal.interactiveshell import TerminalInteractiveShell

from .inject_into_main_thread import inject
from .utils import preserve_sys_state, Singleton
from .tty_utils import PTY, TTYConfig, print_to_ctty


def get_running_app(term_input, term_output):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    kb = KeyBindings()

    @kb.add('c-c')
    def handle_ctrl_c(_event):
        pt_app.app.exit()
        # This is what happens in the parent, is it equivalent?
        # self.set_step()
        # self.set_trace(frame)
        inject()

    pt_app = PromptSession(
        # message=(lambda: PygmentsTokens(get_prompt_tokens())),
        # editing_mode=getattr(EditingMode, self.shell.editing_mode.upper()),
        key_bindings=kb,
        input=term_input,
        output=term_output,
        # TODO: ctrl-r still works??
        enable_history_search=False,
        # history=self.debugger_history,
        # completer=self._ptcomp,
        # enable_history_search=True,
        # mouse_support=self.shell.mouse_support,
        # complete_style=self.shell.pt_complete_style,
        # style=getattr(self.shell, "style", None),
        # color_depth=self.shell.color_depth,
    )
    return pt_app


class RemoteIPythonDebugger(TerminalPdb, metaclass=Singleton):
    _DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'

    def __init__(self):
        self.pty = PTY.open()
        # A patch until https://github.com/ipython/ipython/issues/11745 is solved
        TerminalInteractiveShell.simple_prompt = False
        self.term_input = Vt100Input(self.pty.slave_reader)
        self.term_output = Vt100_Output.from_pty(self.pty.slave_writer)
        super().__init__(pt_session_options=dict(input=self.term_input, output=self.term_output),
                         stdin=self.pty.slave_reader, stdout=self.pty.slave_writer, nosigint=True)
        self.use_rawinput = True
        self.num_clients = 0
        self.done_callbacks = set()
        # TODO: this should be intercepted on the client side to allow force quitting the client
        self.pt_app.key_bindings.remove("c-\\")
        self.running_app = get_running_app(self.term_input, self.term_output)

    def __del__(self):
        print('Closing connection', file=self.pty.slave_writer, flush=True)
        self.pty.close()

    def notify_client_connect(self, tty_config: TTYConfig):
        self.num_clients += 1
        if self.num_clients == 1:
            tty_config.apply(self.pty.slave_fd)
            self.term_output.term = tty_config.term_type
            if self.num_clients == 1:
                inject()

    def notify_client_disconnect(self):
        self.num_clients -= 1
        print(0)
        if self.num_clients == 0:
            # TODO: can we use self.stop_here (from ipython code) instead of the debugging global?
            print(1)
            if self.pt_app.app.is_running:
                print(2)
                self.pt_app.app.exit('quit')
                print(3)
            elif self.running_app.app.is_running:
                print(4)
                # TODO: need to unregister the signal handler
                self.running_app.app.exit()
                print(5)

    def preloop(self):
        if self.num_clients == 0:
            print_to_ctty("Waiting for client to connect")

    def trace_dispatch(self, frame, event, arg, check_debugging_global=False):
        """
        Overriding super to support the check_debugging_global arg.

        :param check_debugging_global: Whether to start debugging only if _DEBUGGING_GLOBAL is in the globals.
        """
        if check_debugging_global:
            if self._DEBUGGING_GLOBAL in frame.f_globals:
                self.set_trace(frame)
            else:
                return None
        bdb_quit = False
        try:
            print('a')
            return super().trace_dispatch(frame, event, arg)
        except BdbQuit:
            bdb_quit = True
        finally:
            print('x')
            if self.quitting or bdb_quit:
                print('y')
                self._on_done()
                print('z')

    def _on_done(self):
        print_to_ctty('Debugger stopped')
        for callback in self.done_callbacks:
            callback()
        self.done_callbacks.clear()

    def do_continue(self, arg):
        """ Overriding super to add a print """
        print('Resuming program, press Ctrl-C to relaunch debugger.', file=self.stdout)
        # TODO: still got the history (c-r) - do we maybe want app run and not app prompt?
        self.thread_executor.submit(self.running_app.prompt)
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
