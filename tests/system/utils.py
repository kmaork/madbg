import os
import re
import socket
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pexpect

SCRIPTS_PATH = Path(__file__).parent / 'scripts'
TIMEOUT = 20
ENV = {**os.environ, 'TERM': 'xterm', 'PROMPT_TOOLKIT_NO_CPR': '1'}
ANSI_ESCAPE = re.compile(r'\x1b(\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])')
DOWN = '\x1b[B'
CTRL_C = '\x03'


def find_free_port() -> int:
    """ A suggested way of finding a free port on the local machine. Prone to race conditions. """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def spawn(*args) -> pexpect.spawn:
    return pexpect.spawn(sys.executable, list(args), dimensions=(50, 150), timeout=TIMEOUT, env=ENV,
                         encoding='utf-8', codec_errors='replace')


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


class Debuggee:
    """ A python script running in its own session, with or without a controlling tty """

    def __init__(self, script: str, *args, with_ctty: bool = True):
        """ :param script: A script name from the scripts dir, or python flags such as -m """
        argv = [script if script.startswith('-') else str(SCRIPTS_PATH / script), *map(str, args)]
        self.with_ctty = with_ctty
        if with_ctty:
            self.process = spawn(*argv)
        else:
            self.process = subprocess.Popen([sys.executable, *argv], env=ENV, start_new_session=True,
                                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True)

    @property
    def pid(self) -> int:
        return self.process.pid

    def wait(self):
        """ :return: The exit code and output of the script """
        if self.with_ctty:
            self.process.expect(pexpect.EOF)
            output = self.process.before
            self.process.close()
            return self.process.exitstatus, strip_ansi(output)
        output, _ = self.process.communicate(timeout=TIMEOUT)
        return self.process.returncode, output

    def kill(self):
        if self.with_ctty:
            self.process.terminate(force=True)
        elif self.process.poll() is None:
            self.process.kill()
            self.process.communicate()


class Client:
    """ A madbg client running in a pty """

    def __init__(self, *madbg_args):
        self.process = spawn('-m', 'madbg', *map(str, madbg_args))

    @classmethod
    def connect(cls, port: int) -> 'Client':
        return cls('connect', '127.0.0.1', port)

    def expect(self, pattern) -> str:
        """ :return: The output up to the pattern, without ansi escapes """
        self.process.expect(pattern)
        return strip_ansi(self.process.before)

    def choose_thread(self, index: int = 0):
        self.expect('Choose a thread')
        # Wait for the whole dialog to be drawn before navigating it
        self.expect(r'Exit')
        self.process.send(DOWN * index + (' ' if index else '') + '\t\r')

    def exit_thread_menu(self):
        self.expect('Choose a thread')
        self.expect(r'Exit')
        self.process.send('\t\t\r')

    def run(self, command: str, thread: str = 'MainThread') -> str:
        """ Wait for a new debugger prompt, run the command and return the output that preceded the prompt """
        # Every new prompt enables bracketed paste
        output = self.expect(r'\x1b\[\?2004h[^\n]*' + thread + '>')
        self.process.send(command + '\r')
        return output

    def wait(self) -> int:
        self.process.expect(pexpect.EOF)
        self.process.close()
        return self.process.exitstatus

    def kill(self):
        self.process.terminate(force=True)
