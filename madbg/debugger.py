from __future__ import annotations

from copy import copy
from dataclasses import dataclass

import runpy
import os
import sys
from bdb import BdbQuit, Bdb
from contextlib import contextmanager, nullcontext
from inspect import currentframe
from sys import _current_frames

from prompt_toolkit.application import create_app_session
from threading import Thread, RLock, Condition
from typing import ContextManager, Callable, Any
from hypno import run_in_thread
from prompt_toolkit import Application, ANSI
from prompt_toolkit.formatted_text import PygmentsTokens
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, WindowAlign
from prompt_toolkit.output.vt100 import Vt100_Output
from IPython.terminal.debugger import TerminalPdb
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from prompt_toolkit.widgets import Label
from pygments.token import Token

from .utils import preserve_sys_state
from .tty_utils import PTY, TTYConfig, print_to_ctty


def exit_app(app: Application, *args):
    """ Thread-safely exit the given app if it is running and wasn't asked to exit already """
    def exit():
        if app.is_running and app.future is not None and not app.future.done():
            app.exit(*args)

    loop = app.loop
    if app.is_running and loop is not None:
        loop.call_soon_threadsafe(exit)


def redraw_app(app: Application):
    """ Thread-safely repaint the whole app, e.g. for a client that just connected to the PTY """
    def redraw():
        app.renderer.reset()
        app.invalidate()

    loop = app.loop
    if app.is_running and loop is not None:
        loop.call_soon_threadsafe(redraw)


class NoClients(Exception):
    """ Exits the debugger prompt when the last client leaves """


def get_running_app(debugger):
    kb = KeyBindings()

    @kb.add('c-c')
    def handle_ctrl_c(_event):
        pt_app.exit()
        debugger.attach()

    @kb.add('q')
    def handle_q(_event):
        pt_app.exit()
        debugger.detach_clients()

    def get_stack(frame):
        stack = []
        while frame is not None:
            stack.append(frame)
            frame = frame.f_back
        return reversed(stack)

    def get_stack_trace():
        # Format with a copy, so the debugger's curframe isn't marked, nor mutated under an interaction's feet
        formatter = copy(debugger)
        formatter.curframe = None
        frame = _current_frames().get(debugger.thread.ident)
        return ANSI(''.join(formatter.format_stack_entry((f, f.f_lineno)) for f in get_stack(frame)))

    pt_app = Application(
        layout=Layout(HSplit([
            Label(f'{debugger.thread.name} - running', align=WindowAlign.CENTER, style='bg:#055515'),
            Label(f'Press Ctrl-C to attach or q to quit\n', align=WindowAlign.CENTER),
            Label(get_stack_trace)
        ])),
        key_bindings=kb,
        input=debugger.term_input,
        output=debugger.term_output,
        erase_when_done=True,
        refresh_interval=0.5,
    )
    pt_app.should_run = lambda: debugger.clients and debugger.resumed
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
                         # nosigint prevents the ipython debugger from registering the sigint handler both for
                         # continue and during command execution, but when ipython doesn't register this handler
                         # during command execution, pdb does
                         stdin=self.pty.slave_io, stdout=self.pty.slave_io, nosigint=True)
        self.use_rawinput = True
        self.clients: set[Client] = set()
        # TODO: this should be intercepted on the client side to allow force quitting the client
        self.pt_app.key_bindings.remove("c-\\")
        self.thread = thread
        # todo: run main debugger prompt in our loop
        self.running_app = get_running_app(self)
        self.check_debugging_global = False
        self.pt_app.app.should_run = lambda: self.clients
        # Guards the clients and the views. Views are level-triggered: each state change calls _update_views,
        # and each view re-checks its should_run in pre_run, as exiting an app that didn't start yet is a no-op.
        self.clients_lock = RLock()
        self.clients_changed = Condition(self.clients_lock)
        # Whether the thread runs freely, i.e. isn't in an interaction or about to enter one. Owned by the thread.
        self.resumed = True
        self.running_app_future = None
        self.post_mortem_message = None

    def _prompt(self):
        """ Overriding super to exit the prompt if it isn't needed by the time it starts """
        with create_app_session():
            return self.pt_app.prompt(pre_run=lambda: self._exit_if_unneeded(self.pt_app.app))

    def _get_prompt(self):
        return PygmentsTokens([(Token.Prompt, f'{self.thread.name}> ')])

    def _exit_if_unneeded(self, app):
        with self.clients_lock:
            if not app.should_run() and app.future is not None and not app.future.done():
                app.exit(exception=NoClients) if app is self.pt_app.app else app.exit()

    def _update_views(self):
        """ Called with clients_lock held whenever clients or resumed change """
        for app in (self.pt_app.app, self.running_app):
            if app.is_running and app.loop is not None:
                app.loop.call_soon_threadsafe(self._exit_if_unneeded, app)
        if self.running_app.should_run() and (self.running_app_future is None or self.running_app_future.done()):
            self.running_app_future = self.thread_executor.submit(self._run_running_app)

    def _run_running_app(self):
        with create_app_session():
            self.running_app.run(pre_run=lambda: self._exit_if_unneeded(self.running_app))

    def attach(self):
        def set():
            if not self.resumed:
                # Resetting the debugger during cmdloop would unset self.curframe under its feet
                return
            f = currentframe().f_back.f_back.f_back
            f.f_globals[self._DEBUGGING_GLOBAL] = True
            self.check_debugging_global = True
            self.set_trace(f)

        # If this gets stuck, it's probably because the debugger kicks in before the injection finishes.
        # The debugging global must be pushed to the right frame to prevent that.
        run_in_thread(self.thread, set)

    def _configure_tty(self):
        with self.clients_lock:
            if len(self.clients) == 1:
                tty_config = next(iter(self.clients)).config
                tty_config.apply(self.pty.slave_fd)
                self.term_output.term = tty_config.term_type
                self.term_input.term = tty_config.term_type

    def add_client(self, client: Client):
        with self.clients_lock:
            self.clients.add(client)
            self._configure_tty()
            self.clients_changed.notify_all()
            for app in (self.pt_app.app, self.running_app):
                redraw_app(app)
            self._update_views()

    def remove_client(self, client: Client):
        with self.clients_lock:
            if client in self.clients:
                self.clients.remove(client)
                self._configure_tty()
                self._update_views()

    def _set_resumed(self, resumed):
        with self.clients_lock:
            self.resumed = resumed
            self._update_views()

    def interaction(self, frame, traceback):
        self._set_resumed(False)
        try:
            with self.clients_lock:
                if not self.clients:
                    print_to_ctty(f'Madbg - {self.thread.name} is waiting for a client to connect')
                    self.clients_changed.wait_for(lambda: self.clients)
            if self.post_mortem_message is not None:
                print(self.post_mortem_message, file=self.stdout)
                self.post_mortem_message = None
            super().interaction(frame, traceback)
        except NoClients:
            # Resume the thread, like quit but without detaching clients that connected meanwhile
            self.forget()
            Bdb.set_quit(self)
        finally:
            # Show the running view unless the thread is about to stop again, e.g. after a step
            self._set_resumed(self.quitting or self.stoplineno == -1)

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
        try:
            return super().trace_dispatch(frame, event, arg)
        except BdbQuit:
            pass

    def set_quit(self):
        """ Called by the quit commands, including EOF. Returns the clients that saw the quit to the thread menu. """
        self.detach_clients()
        super().set_quit()

    def detach_clients(self):
        with self.clients_lock:
            for client in self.clients:
                client.on_detach()
            self.clients.clear()
            self._update_views()

    def post_mortem(self, traceback, message=None):
        self.reset()
        self.post_mortem_message = message
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
