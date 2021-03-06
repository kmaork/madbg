import runpy
import os
import sys
import traceback
from bdb import BdbQuit
from contextlib import contextmanager, nullcontext
from IPython.terminal.debugger import TerminalPdb
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output

from .utils import preserve_sys_state, get_client_connection, use_context
from .tty_utils import print_to_ctty, open_pty, resize_terminal, modify_terminal, set_ctty
from .communication import receive_message, pipe_in_background


class RemoteIPythonDebugger(TerminalPdb):
    """
    Initializes IPython's TerminalPdb with stdio from a pty.
    As TerminalPdb uses prompt_toolkit instead of the builtin input(),
    we can use it to allow line editing and tab completion for files other than stdio (in this case, the pty).
    Because we need to provide the stdin and stdout params to the __init__, and they require a connection to the client,
    """
    DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'

    # TODO: should this be a per-thread singleton? Because sys.settrace is singletonic

    def __init__(self, stdin, stdout, term_type):
        # A patch until https://github.com/ipython/ipython/issues/11745 is solved
        TerminalInteractiveShell.simple_prompt = False
        term_input = Vt100Input(stdin)
        term_output = Vt100_Output.from_pty(stdout, term_type)
        super().__init__(pt_session_options=dict(input=term_input, output=term_output), stdin=stdin, stdout=stdout)
        self.use_rawinput = True

    def trace_dispatch(self, frame, event, arg, check_debugging_global=False, done_callback=None):
        """
        Overriding super to allow the check_debugging_global and done_callback args.

        :param check_debugging_global: Whether to start debugging only if DEBUGGING_GLOBAL is in the globals.
        :param done_callback: a callable to be called when the debug session ends.
        """
        if check_debugging_global:
            if self.DEBUGGING_GLOBAL in frame.f_globals:
                self.set_trace(frame, done_callback=done_callback)
            else:
                return
        bdb_quit = False
        try:
            return super().trace_dispatch(frame, event, arg)
        except BdbQuit:
            bdb_quit = True
        finally:
            if (done_callback is not None) and (self.quitting or bdb_quit):
                done_callback()

    def set_trace(self, frame=None, done_callback=None):
        """ Overriding super to add the done_callback argument, allowing cleanup after a debug session """
        td = lambda *args: self.trace_dispatch(*args, done_callback=done_callback)
        if frame is None:
            frame = sys._getframe().f_back
        self.reset()
        while frame:
            frame.f_trace = td
            self.botframe = frame
            frame = frame.f_back
        self.set_step()
        sys.settrace(td)

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
        globals = {self.DEBUGGING_GLOBAL: True}
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
    def debug(self, check_debugging_global=False):
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
    def connect_and_set_trace(cls, ip, port, frame=None):
        if frame is None:
            frame = sys._getframe().f_back
        debugger, exit_stack = use_context(cls.connect_and_start(ip, port))
        debugger.set_trace(frame, done_callback=exit_stack.close)

    @classmethod
    @contextmanager
    def start(cls, sock_fd):
        term_data = receive_message(sock_fd)
        term_attrs, term_type, term_size = term_data['term_attrs'], term_data['term_type'], term_data['term_size']
        with open_pty() as (master_fd, slave_fd):
            resize_terminal(slave_fd, term_size[0], term_size[1])
            modify_terminal(slave_fd, term_attrs)
            set_ctty(slave_fd)
            with pipe_in_background({sock_fd: master_fd, master_fd: sock_fd}):
                slave_reader = os.fdopen(slave_fd, 'r')
                slave_writer = os.fdopen(slave_fd, 'w')
                try:
                    yield cls(slave_reader, slave_writer, term_type)
                except Exception:
                    print(traceback.format_exc(), file=slave_writer)
                    raise
                finally:
                    # We flush to make sure the message is written before the last pipe iteration
                    print('Closing connection', file=slave_writer, flush=True)
                    # TODO: solve race
                    import time
                    time.sleep(0.05)

    @classmethod
    @contextmanager
    def connect(cls, ip, port):
        print_to_ctty(f'Waiting for connection from debugger console on {ip}:{port}')
        with get_client_connection(ip, port) as sock_fd:
            yield sock_fd

    @classmethod
    @contextmanager
    def connect_and_start(cls, ip, port):
        with cls.connect(ip, port) as sock_fd:
            with cls.start(sock_fd) as debugger:
                yield debugger
