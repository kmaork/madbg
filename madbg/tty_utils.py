from __future__ import annotations
import errno
import os
import pty
import struct
import tty
from dataclasses import dataclass
import fcntl
import termios
from functools import cached_property
from typing import Tuple


@dataclass
class TTYConfig:
    term_attrs: list
    term_type: str
    term_size: Tuple[int, int]

    @classmethod
    def get(cls, slave_fd: int) -> TTYConfig:
        term_size = os.get_terminal_size(slave_fd)
        return cls(term_attrs=termios.tcgetattr(slave_fd),
                   # prompt toolkit will receive this string, and it can be 'unknown'
                   term_type=os.environ.get("TERM", "unknown"),
                   term_size=(term_size.lines, term_size.columns))

    def _resize(self, slave_fd: int):
        winsize = struct.pack("HHHH", *self.term_size, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    def _set_tty_attrs(self, slave_fd: int, when=termios.TCSANOW):
        IFLAG, OFLAG, CFLAG, LFLAG, ISPEED, OSPEED, CC = range(7)
        tc_attrs = self.term_attrs[:]
        current_attrs = termios.tcgetattr(slave_fd)
        tc_attrs[CC] = current_attrs[CC]
        termios.tcsetattr(slave_fd, when, tc_attrs)

    def apply(self, slave_fd: int):
        self._resize(slave_fd)
        # TODO: remove or fix
        # self._set_tty_attrs(slave_fd)


@dataclass
class PTY:
    master_fd: int
    slave_fd: int
    _closed: bool = False

    @cached_property
    def slave_reader(self):
        # TODO: pass closefd?
        return os.fdopen(self.slave_fd, 'r')

    @cached_property
    def slave_writer(self):
        return os.fdopen(self.slave_fd, 'w')

    def close(self):
        if not self._closed:
            termios.tcdrain(self.slave_fd)
            os.close(self.master_fd)
            self._closed = True

    def set_raw(self):
        tty.setraw(self.slave_fd, termios.TCSANOW)

    @classmethod
    def open(cls) -> PTY:
        master_fd, slave_fd = pty.openpty()
        return cls(master_fd, slave_fd)


def print_to_ctty(*args):
    """ If there is a ctty, print the given string to it. """
    try:
        with open(os.ctermid(), 'w') as tty:
            print(*args, file=tty)
    except OSError as e:
        if e.errno != errno.ENXIO:
            raise
