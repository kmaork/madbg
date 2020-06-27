import errno
import runpy
import atexit
import os
from bdb import BdbQuit
from IPython.terminal.debugger import *
from concurrent.futures import Future
from contextlib import contextmanager, nullcontext
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output

from .utils import preserve_sys_state, remote_pty
from .tty_utils import print_to_ctty


class RemoteIPythonDebugger(TerminalPdb):
    """
    Initializes IPython's TerminalPdb with stdio from a pty.
    As TerminalPdb uses prompt_toolkit instead of the builtin input(),
    we can use it to allow line editing and tab completion for files other than stdio (in this case, the pty).
    Because we need to provide the stdin and stdout params to the __init__, and they require a connection to the client,
    """
    DEBUGGING_GLOBAL = 'DEBUGGING_WITH_MADBG'

    # TODO: this should be a thread safe singleton

    def __init__(self, ip, port):
        self.on_shutdown = Future()
        self._remote_pty_ctx_manager = remote_pty(ip, port, self.on_shutdown)
        self._entered_remote_pty_ctx_manager = False
        atexit.register(self.shutdown)
        # TODO: is this the right way to do this?
        print_to_ctty('Waiting for connection from debugger console on {}:{}'.format(ip, port))
        slave_fd, self.term_type = self._remote_pty_ctx_manager.__enter__()  # TODO: this is pretty ugly
        self._entered_remote_pty_ctx_manager = True
        # TODO: print that we connected before detaching ctty
        super().__init__(stdin=os.fdopen(slave_fd, 'r'), stdout=os.fdopen(slave_fd, 'w'))
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

    def shutdown(self):
        if not self.on_shutdown.done():
            self.on_shutdown.set_result(None)
            atexit.unregister(self.shutdown)
            if self._entered_remote_pty_ctx_manager:
                try:
                    print('Exiting debugger', file=self.stdout)
                except OSError as e:
                    if e.errno != errno.EBADF:
                        raise
                self._remote_pty_ctx_manager.__exit__(None, None, None)

    def trace_dispatch(self, frame, event, arg, check_debugging_global=False):
        if check_debugging_global:
            # print(frame.f_code.co_filename, self.DEBUGGING_GLOBAL in frame.f_globals, '\r')
            # if frame.f_code.co_filename == '/tmp/lol.py':
            #     print(frame.f_globals, '\r')
            if self.DEBUGGING_GLOBAL in frame.f_globals:
                self.set_trace(frame)
            return
        try:
            super().trace_dispatch(frame, event, arg)
        except BdbQuit:
            self.quitting = True
        except:
            self.shutdown()
            raise
        if self.quitting:
            self.shutdown()

    def post_mortem(self, traceback):
        self.reset()
        self.interaction(None, traceback)

    def do_continue(self, arg):
        if not self.nosigint:
            print('Resuming program, press Ctrl-C to relaunch debugger. Use q to exit.', file=self.stdout)
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

# TODO: tests for apis
# TODO: add tox
# TODO: weird exception if pressing a lot of nexts
# TODO: support python2? or completely python3
# TODO: if sys.trace changes (ipdb in a loop), we don't close socket
# TODO: handle client death
# TODO: bugs when connecting to debugger twice. Use that to identify remaining state from debugger
# TODO: add test for debugging twice
