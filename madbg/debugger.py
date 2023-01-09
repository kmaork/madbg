from __future__ import annotations

from dataclasses import dataclass

import runpy
import os
import sys
from asyncio import AbstractEventLoop
from bdb import BdbQuit
from contextlib import contextmanager, nullcontext
from inspect import currentframe
from threading import Thread
from typing import ContextManager, Callable, Any
from hypno import run_in_thread
from prompt_toolkit import Application
from prompt_toolkit.formatted_text import PygmentsTokens
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.output.vt100 import Vt100_Output
from IPython.terminal.debugger import TerminalPdb
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from prompt_toolkit.widgets import Label
from pygments.token import Token

from .utils import preserve_sys_state
from .tty_utils import PTY, TTYConfig, print_to_ctty


def get_running_app(debugger):
    kb = KeyBindings()

    @kb.add('c-c')
    def handle_ctrl_c(_event):
        pt_app.exit()
        debugger.attach()

    pt_app = Application(
        layout=Layout(Label('Press Ctrl-C to attach')),
        key_bindings=kb,
        input=debugger.term_input,
        output=debugger.term_output,
        erase_when_done=True,
    )
    return pt_app


@dataclass
class Client:
    config: TTYConfig
    on_detach: Callable[[], Any]

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


class RemoteIPythonDebugger(TerminalPdb):
    _DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'

    def __init__(self, thread: Thread, pty: PTY):
        self.pty = pty
        # A patch until https://github.com/ipython/ipython/issues/11745 is solved
        TerminalInteractiveShell.simple_prompt = False
        self.term_input = Vt100Input(self.pty.slave_io)
        self.term_output = Vt100_Output.from_pty(self.pty.slave_io)
        super().__init__(pt_session_options=dict(input=self.term_input, output=self.term_output,
                                                 message=self._get_prompt),
                         stdin=self.pty.slave_io, stdout=self.pty.slave_io, nosigint=True)
        self.use_rawinput = True
        self.clients: set[Client] = set()
        # TODO: this should be intercepted on the client side to allow force quitting the client
        self.pt_app.key_bindings.remove("c-\\")
        self.thread = thread
        # todo: run main debugger prompt in our loop
        self.running_app = get_running_app(self)
        self.check_debugging_global = False

    def _get_prompt(self):
        return PygmentsTokens([(Token.Prompt, f'{self.thread.name}> ')])

    def attach(self):
        def set():
            f = currentframe().f_back.f_back.f_back
            f.f_globals[self._DEBUGGING_GLOBAL] = True
            self.check_debugging_global = True
            self.set_trace(f)
        # If this gets stuck, it's probably because the debugger kicks in before the injection finishes.
        # The debugging global must be pushed to the right frame to prevent that.
        run_in_thread(self.thread, set)

    def _configure_tty(self):
        if len(self.clients) == 1:
            tty_config = next(iter(self.clients)).config
            tty_config.apply(self.pty.slave_fd)
            self.term_output.term = tty_config.term_type
            self.term_input.term = tty_config.term_type

    def add_client(self, client: Client):
        self.clients.add(client)
        self._configure_tty()
        self._run_running_app()

    def remove_client(self, client: Client):
        if client in self.clients:
            self.clients.remove(client)
            self._configure_tty()
            if not self.clients:
                # TODO: can we use self.stop_here (from ipython code) instead of the debugging global?
                if self.pt_app.app.is_running:
                    self.pt_app.app.exit('quit')
                if self.running_app.is_running:
                    self.running_app.exit()

    def preloop(self):
        if not self.clients:
            print_to_ctty("Waiting for client to connect")

    def trace_dispatch(self, frame, event, arg):
        """
        Overriding super to support check_debugging_global and on_done.
        """
        if self.check_debugging_global:
            if self._DEBUGGING_GLOBAL in frame.f_globals:
                self.check_debugging_global = False
                del frame.f_globals[self._DEBUGGING_GLOBAL]
            else:
                return self.trace_dispatch
        bdb_quit = False
        try:
            s = super().trace_dispatch(frame, event, arg)
            return s
        except BdbQuit:
            bdb_quit = True
        finally:
            if self.quitting or bdb_quit:
                self._on_done()

    def _on_done(self):
        for client in self.clients:
            client.on_detach()
        self.clients.clear()

    def _run_running_app(self):
        self.thread_executor.submit(self.running_app.run)

    def do_continue(self, arg):
        self._run_running_app()
        # This doesn't register a SIGINT handler as we set self.nosigint to True
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
            self.check_debugging_global = True
            try:
                with self.debug() if set_trace else nullcontext():
                    if run_as_module:
                        runpy.run_module(python_file, alter_sys=True, run_name=run_name, init_globals=globals)
                    else:
                        runpy.run_path(python_file, run_name=run_name, init_globals=globals)
            finally:
                self.check_debugging_global = False

    @contextmanager
    def debug(self) -> ContextManager:
        self.reset()
        sys.settrace(lambda *args: self.trace_dispatch(*args))
        try:
            yield
        except BdbQuit:
            pass
        finally:
            self.quitting = True
            sys.settrace(None)
