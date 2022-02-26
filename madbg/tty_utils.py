from __future__ import annotations
import errno
import os
import pty
import struct
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from multiprocessing.pool import Pool
import signal
import fcntl
from typing import Optional, Tuple

import termios


def is_session_leader():
    return os.getsid(0) == os.getpid()


def set_group_leader():
    os.setpgid(0, 0)
    return os.getpgid(0)


def make_sure_not_group_leader():
    if os.getpgid(0) == os.getpid():
        with Pool(1) as pool:
            pgid = pool.apply(set_group_leader)
            os.setpgid(0, pgid)


def make_session_leader():
    make_sure_not_group_leader()
    os.setsid()


@contextmanager
def set_handler(sig, handler):
    old = signal.signal(sig, handler)
    try:
        yield old
    finally:
        signal.signal(sig, old)


def ignore_signal(sig):
    return set_handler(sig, signal.SIG_IGN)


def detach_ctty(ctty_fd):
    # TODO: will children receive sighup as well?
    # When a process detaches from a tty, it is sent the signals SIGHUP and then SIGCONT
    with ignore_signal(signal.SIGHUP):
        fcntl.ioctl(ctty_fd, termios.TIOCNOTTY)


def attach_ctty(fd: int) -> bool:
    try:
        fcntl.ioctl(fd, termios.TIOCSCTTY, 1)
        return True
    except PermissionError:
        return False


def get_ctty_fd() -> Optional[int]:
    """
    If there is a controlling tty for this process, return a read+write fd to it.
    Otherwise return None.
    """
    try:
        return os.open(os.ctermid(), os.O_RDWR)
    except OSError as e:
        if e.errno == errno.ENXIO:
            return None
        raise


def detach_current_ctty():
    """ Detach from ctty if there is one """
    ctty_fd = get_ctty_fd()
    # If there is no ctty, ctty_fd is None and we don't do anything
    if ctty_fd is not None:
        if is_session_leader():
            detach_ctty(ctty_fd)
        else:
            make_session_leader()
        os.close(ctty_fd)


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
            with ignore_signal(signal.SIGHUP):
                os.close(self.master_fd)
            self._closed = True

    def make_ctty(self) -> bool:
        detach_current_ctty()
        return attach_ctty(self.slave_fd)

    @classmethod
    def open(cls) -> PTY:
        master_fd, slave_fd = pty.openpty()
        return cls(master_fd, slave_fd)


def print_to_ctty(string):
    """ If there is a ctty, print the given string to it. """
    ctty_fd = get_ctty_fd()
    if ctty_fd is not None:
        print(string, file=os.fdopen(ctty_fd, 'w'))
