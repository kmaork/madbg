from __future__ import annotations
import runpy
import os
import socket
import sys
import traceback
from bdb import BdbQuit
from contextlib import contextmanager, nullcontext
from termios import tcdrain
from typing import Optional, ContextManager

from IPython.terminal.debugger import TerminalPdb
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output
from inspect import currentframe

from .utils import preserve_sys_state, run_thread
from .tty_utils import print_to_ctty, PTY
from .communication import receive_message, Piping


class RemoteIPythonDebugger(TerminalPdb):
    """
    Initializes IPython's TerminalPdb with stdio from a pty.
    As TerminalPdb uses prompt_toolkit instead of the builtin input(),
    we can use it to allow line editing and tab completion for files other than stdio (in this case, the pty).
    Because we need to provide the stdin and stdout params to the __init__, and they require a connection to the client,
    """
    _DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'
    _CURRENT_INSTANCE = None

    @classmethod
    def _get_current_instance(cls) -> Optional[RemoteIPythonDebugger]:
        return cls._CURRENT_INSTANCE

    @classmethod
    def _set_current_instance(cls, new: Optional[RemoteIPythonDebugger]) -> None:
        cls._CURRENT_INSTANCE = new

    def __init__(self, stdin, stdout, term_type):
        # A patch until https://github.com/ipython/ipython/issues/11745 is solved
        TerminalInteractiveShell.simple_prompt = False
        term_input = Vt100Input(stdin)
        term_output = Vt100_Output.from_pty(stdout, term_type)
        super().__init__(pt_session_options=dict(input=term_input, output=term_output), stdin=stdin, stdout=stdout)
        self.use_rawinput = True
        self.done_callback = None

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

    @classmethod
    @contextmanager
    def start(cls, sock_fd: int) -> ContextManager[RemoteIPythonDebugger]:
        # TODO: just add to pipe list
        assert cls._get_current_instance() is None
        term_data = receive_message(sock_fd)
        term_attrs, term_type, term_size = term_data['term_attrs'], term_data['term_type'], term_data['term_size']
        with PTY.open() as pty:
            pty.resize(term_size[0], term_size[1])
            pty.set_tty_attrs(term_attrs)
            pty.make_ctty()
            piping = Piping({sock_fd: {pty.master_fd}, pty.master_fd: {sock_fd}})
            with run_thread(piping.run):
                slave_reader = os.fdopen(pty.slave_fd, 'r')
                slave_writer = os.fdopen(pty.slave_fd, 'w')
                try:
                    instance = cls(slave_reader, slave_writer, term_type)
                    cls._set_current_instance(instance)
                    yield instance
                except Exception:
                    print(traceback.format_exc(), file=slave_writer)
                    raise
                finally:
                    cls._set_current_instance(None)
                    print('Closing connection', file=slave_writer, flush=True)
                    tcdrain(pty.slave_fd)
                    slave_writer.close()

    @classmethod
    @contextmanager
    def get_server_socket(cls, ip: str, port: int) -> ContextManager[socket.socket]:
        """
        Return a new server socket for client to connect to. The caller is responsible for closing it.
        """
        server_socket = socket.socket()
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        server_socket.bind((ip, port))
        try:
            yield server_socket
        finally:
            server_socket.close()

    @classmethod
    @contextmanager
    def start_from_new_connection(cls, sock: socket.socket) -> ContextManager[RemoteIPythonDebugger]:
        print_to_ctty(f'Debugger client connected from {sock.getpeername()}')
        try:
            with cls.start(sock.fileno()) as debugger:
                yield debugger
        finally:
            sock.close()

    @classmethod
    def connect_and_start(cls, ip: str, port: int) -> ContextManager[RemoteIPythonDebugger]:
        # TODO: get rid of context managers at some level - nobody is going to use with start() anyway
        current_instance = cls._get_current_instance()
        if current_instance is not None:
            return nullcontext(current_instance)
        with cls.get_server_socket(ip, port) as server_socket:
            server_socket.listen(1)
            print_to_ctty(f'Waiting for debugger client on {ip}:{port}')
            sock, _ = server_socket.accept()
        return cls.start_from_new_connection(sock)
