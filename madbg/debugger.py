import errno
import select
from bdb import BdbQuit

from IPython.terminal.debugger import *
import atexit
import socket
import os
from concurrent.futures import ThreadPoolExecutor, Future
from contextlib import contextmanager
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output

from .tty_utils import set_ctty, resize_terminal, modify_terminal, open_pty, print_to_ctty
from .communication import pipe, receive_message
from .utils import LazyInit


class ConnectionCancelled(Exception):
    pass


@contextmanager
def get_client_connection(ip, port, cancelled_future=None):
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    server_socket.bind((ip, port))
    server_socket.listen(1)
    while not select.select([server_socket], [], [], 0.1)[0]:
        if cancelled_future is not None and cancelled_future.done():
            raise ConnectionCancelled()
    sock, _ = server_socket.accept()
    server_socket.close()
    try:
        yield sock.fileno()
    finally:
        sock.close()


@contextmanager
def remote_pty(ip, port, cancelled_future=None):
    with get_client_connection(ip, port, cancelled_future) as sock:
        # TODO: should we set settings like that, or just write some ansi? https://apple.stackexchange.com/questions/33736/can-a-terminal-window-be-resized-with-a-terminal-command
        term_data = receive_message(sock)
        term_attrs, term_type, term_size = term_data['term_attrs'], term_data['term_type'], term_data['term_size']
        # TODO: what is the correct term type? the pty or the remote tty?
        with open_pty() as (master_fd, slave_fd):
            resize_terminal(slave_fd, term_size[0], term_size[1])
            modify_terminal(slave_fd, term_attrs)
            with set_ctty(slave_fd):
                ThreadPoolExecutor(1).submit(pipe, {sock: master_fd, master_fd: sock})  # TODO: join the thread sometime
                yield slave_fd, term_type


class RemoteIPythonDebugger(TerminalPdb, metaclass=LazyInit):
    """
    Initializes IPython's TerminalPdb with stdio from a pty.
    As TerminalPdb uses prompt_toolkit instead of the builtin input(),
    we can use it to allow line editing and tab completion for files other than stdio (in this case, the pty).
    Because we need to provide the stdin and stdout params to the __init__, and they require a connection to the client,
    we use the LazyInit metaclass to allow instantiation before having to actually connect.
    """

    # TODO: this should be a thread safe singleton

    def __init__(self, ip, port):
        # TODO: allow returning pty before connecting to client, so we don't have to use LazyInit
        self.on_shutdown = Future()
        self._remote_pty_ctx_manager = remote_pty(ip, port, self.on_shutdown)
        self._entered_remote_pty_ctx_manager = False
        atexit.register(self.shutdown)
        # TODO: is this the right way to do this?
        print_to_ctty('Waiting for connection from debugger console on {}:{}'.format(ip, port))
        slave_fd, self.term_type = self._remote_pty_ctx_manager.__enter__()  # TODO: this is pretty ugly
        self._entered_remote_pty_ctx_manager = True
        # TODO: print that we connected before detaching ctty
        super(RemoteIPythonDebugger, self).__init__(stdin=os.fdopen(slave_fd, 'r'), stdout=os.fdopen(slave_fd, 'w'))
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
        options = options.update(pt_session_options)
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

    def trace_dispatch(self, frame, event, arg):
        try:
            super(RemoteIPythonDebugger, self).trace_dispatch(frame, event, arg)
        except BdbQuit:
            self.quitting = True
        except:
            self.shutdown()
            raise
        if self.quitting:
            self.shutdown()

    def set_sys_trace(self):
        sys.settrace(self.trace_dispatch)

    def post_mortem(self, traceback):
        self.reset()
        self.interaction(None, traceback)

    def do_continue(self, arg):
        if not self.nosigint:
            print('Resuming program, press Ctrl-C to relaunch debugger. Use q to exit.', file=self.stdout)
        return super(RemoteIPythonDebugger, self).do_continue(arg)

    do_c = do_cont = do_continue

# TODO: tests for apis
# TODO: add tox
# TODO: weird exception if pressing a lot of nexts
# TODO: support python2? or completely python3
# TODO: if sys.trace changes (ipdb in a loop), we don't close socket
# TODO: handle client death
# TODO: bugs when connecting to debugger twice. Use that to identify remaining state from debugger
# TODO: add test for debugging twice
