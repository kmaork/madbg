import runpy
import os
from concurrent.futures.thread import ThreadPoolExecutor
from bdb import BdbQuit
from IPython.terminal.debugger import *
from contextlib import contextmanager, nullcontext
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output

from .utils import preserve_sys_state, get_client_connection, use_context
from .tty_utils import print_to_ctty, open_pty, resize_terminal, modify_terminal, set_ctty
from .communication import receive_message, pipe


class RemoteIPythonDebugger(TerminalPdb):
    """
    Initializes IPython's TerminalPdb with stdio from a pty.
    As TerminalPdb uses prompt_toolkit instead of the builtin input(),
    we can use it to allow line editing and tab completion for files other than stdio (in this case, the pty).
    Because we need to provide the stdin and stdout params to the __init__, and they require a connection to the client,
    """
    DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'

    # TODO: this should be a thread safe singleton

    def __init__(self, stdin, stdout, term_type):
        self.term_type = term_type
        super().__init__(stdin=stdin, stdout=stdout)
        self.use_rawinput = True

    def pt_init(self, pt_session_options=None):
        """Initialize the prompt session and the prompt loop
        and store them in self.pt_app and self.pt_loop.
        
        Additional keyword arguments for the PromptSession class
        can be specified in pt_session_options.
        """
        if pt_session_options is None:
            pt_session_options = {}

        def get_prompt_tokens():
            return [(Token.Prompt, self.prompt)]

        if self._ptcomp is None:
            compl = IPCompleter(shell=self.shell,
                                namespace={},
                                global_namespace={},
                                parent=self.shell,
                                )
            # add a completer for all the do_ methods
            methods_names = [m[3:] for m in dir(self) if m.startswith("do_")]

            def gen_comp(self, text):
                return [m for m in methods_names if m.startswith(text)]

            import types
            newcomp = types.MethodType(gen_comp, compl)
            compl.custom_matchers.insert(0, newcomp)
            # end add completer.

            self._ptcomp = IPythonPTCompleter(compl)

        options = dict(
            message=(lambda: PygmentsTokens(get_prompt_tokens())),
            editing_mode=getattr(EditingMode, self.shell.editing_mode.upper()),
            key_bindings=create_ipython_shortcuts(self.shell),
            history=self.shell.debugger_history,
            completer=self._ptcomp,
            enable_history_search=True,
            mouse_support=self.shell.mouse_support,
            complete_style=self.shell.pt_complete_style,
            style=self.shell.style,
            color_depth=self.shell.color_depth,
            input=Vt100Input(self.stdin),
            output=Vt100_Output.from_pty(self.stdout, self.term_type)
        )

        if not PTK3:
            options['inputhook'] = self.shell.inputhook
        options.update(pt_session_options)
        self.pt_loop = asyncio.new_event_loop()
        self.pt_app = PromptSession(**options)

    def trace_dispatch(self, frame, event, arg, check_debugging_global=False, done_callback=None):
        if check_debugging_global:
            if self.DEBUGGING_GLOBAL in frame.f_globals:
                self.set_trace(frame)
            else:
                return
        bdb_quit = False
        try:
            super().trace_dispatch(frame, event, arg)
        except BdbQuit:
            bdb_quit = True
            raise
        finally:
            if (done_callback is not None) and (self.quitting or bdb_quit):
                done_callback()

    def set_trace(self, frame=None, done_callback=None):
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

    def post_mortem(self, traceback):
        self.reset()
        self.interaction(None, traceback)

    def do_continue(self, arg):
        if not self.nosigint:
            print('Resuming program, press Ctrl-C to relaunch debugger.', file=self.stdout)
        return super().do_continue(arg)

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

    do_c = do_cont = do_continue

    @classmethod
    def connect_and_set_trace(cls, ip, port, frame=None):
        if frame is None:
            frame = sys._getframe().f_back
        debugger, exit_stack = use_context(cls.connect_and_start(ip, port))
        debugger.set_trace(frame, exit_stack.close)

    @classmethod
    @contextmanager
    def start(cls, sock):
        # TODO: should we set settings like that, or just write some ansi? https://apple.stackexchange.com/questions/33736/can-a-terminal-window-be-resized-with-a-terminal-command
        term_data = receive_message(sock)
        term_attrs, term_type, term_size = term_data['term_attrs'], term_data['term_type'], term_data['term_size']
        # TODO: what is the correct term type? the pty or the remote tty?
        with open_pty() as (master_fd, slave_fd):
            resize_terminal(slave_fd, term_size[0], term_size[1])
            modify_terminal(slave_fd, term_attrs)
            set_ctty(slave_fd)
            # TODO: join the thread sometime
            with ThreadPoolExecutor(1) as exec:
                future = exec.submit(pipe, {sock: master_fd, master_fd: sock})
                slave_reader = os.fdopen(slave_fd, 'r')
                slave_writer = os.fdopen(slave_fd, 'w')
                yield RemoteIPythonDebugger(slave_reader, slave_writer, term_type)
                print('Closing connection', file=slave_writer)
                os.close(slave_fd)
                future.result()
        future.result()

    @classmethod
    @contextmanager
    def connect(cls, ip, port):
        print_to_ctty('Waiting for connection from debugger console on {}:{}'.format(ip, port))
        with get_client_connection(ip, port) as sock:
            yield sock

    @classmethod
    @contextmanager
    def connect_and_start(cls, ip, port):
        with cls.connect(ip, port) as sock:
            with cls.start(sock) as debugger:
                yield debugger

# TODO: tests for apis
# TODO: add tox
# TODO: weird exception if pressing a lot of nexts
# TODO: support python2? or completely python3
# TODO: if sys.trace changes (ipdb in a loop), we don't close socket
# TODO: handle client death
# TODO: bugs when connecting to debugger twice. Use that to identify remaining state from debugger
# TODO: add test for debugging twice
