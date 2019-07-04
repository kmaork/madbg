from bdb import BdbQuit

from IPython.terminal.debugger import *
import atexit
import socket
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from prompt_toolkit.input.vt100 import Vt100Input
from prompt_toolkit.output.vt100 import Vt100_Output

from .tty_utils import set_ctty, resize_terminal, modify_terminal, open_pty
from .communication import pipe, receive_message


@contextmanager
def get_client_connection(ip, port):
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    server_socket.bind((ip, port))
    server_socket.listen(1)
    sock, _ = server_socket.accept()
    server_socket.close()
    try:
        yield sock.fileno()
    finally:
        sock.close()


@contextmanager
def remote_pty(ip, port):
    with get_client_connection(ip, port) as sock:
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


class RemoteIPythonDebugger(TerminalPdb):
    def __init__(self, ip, port):
        self._remote_pty_ctx_manager = remote_pty(ip, port)
        # TODO: that should happen in trace_dispatch()
        slave_fd, self.term_type = self._remote_pty_ctx_manager.__enter__()  # TODO: this is pretty ugly
        atexit.register(self.shutdown)
        super(RemoteIPythonDebugger, self).__init__(stdin=os.fdopen(slave_fd, 'r'), stdout=os.fdopen(slave_fd, 'w'))
        self.use_rawinput = True

    def pt_init(self):
        """
        Copy of super, because we need to add input and output params to PromptSession
        """

        # TODO: open another PR to ipython, allowing to delete this duplication
        def get_prompt_tokens():
            return [(Token.Prompt, self.prompt)]

        if self._ptcomp is None:
            compl = IPCompleter(shell=self.shell,
                                namespace={},
                                global_namespace={},
                                parent=self.shell,
                                )
            self._ptcomp = IPythonPTCompleter(compl)

        kb = KeyBindings()
        supports_suspend = Condition(lambda: hasattr(signal, 'SIGTSTP'))
        kb.add('c-z', filter=supports_suspend)(suspend_to_bg)

        if self.shell.display_completions == 'readlinelike':
            kb.add('tab', filter=(has_focus(DEFAULT_BUFFER)
                                  & ~has_selection
                                  & vi_insert_mode | emacs_insert_mode
                                  & ~cursor_in_leading_ws
                                  ))(display_completions_like_readline)

        self.pt_app = PromptSession(
            message=(lambda: PygmentsTokens(get_prompt_tokens())),
            editing_mode=getattr(EditingMode, self.shell.editing_mode.upper()),
            key_bindings=kb,
            history=self.shell.debugger_history,
            completer=self._ptcomp,
            enable_history_search=True,
            mouse_support=self.shell.mouse_support,
            complete_style=self.shell.pt_complete_style,
            style=self.shell.style,
            inputhook=self.shell.inputhook,
            color_depth=self.shell.color_depth,
            input=Vt100Input(self.stdin),
            output=Vt100_Output.from_pty(self.stdout, self.term_type)
        )  # TODO: understand prompt toolkit implementation

    def shutdown(self):
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
