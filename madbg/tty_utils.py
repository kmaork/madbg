import errno
import os
import pty
import struct
from contextlib import contextmanager
from multiprocessing.pool import Pool
import signal
import fcntl
from typing import Optional

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
def ignore_signal(signal_num: int):
    old = signal.signal(signal_num, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal_num, old)


def detach_ctty(ctty_fd):
    # TODO: will children receive sighup as well?
    # When a process detaches from a tty, it is sent the signals SIGHUP and then SIGCONT
    with ignore_signal(signal.SIGHUP):
        fcntl.ioctl(ctty_fd, termios.TIOCNOTTY)


def attach_ctty(fd):
    fcntl.ioctl(fd, termios.TIOCSCTTY, 1)


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


def set_ctty(fd):
    detach_current_ctty()
    attach_ctty(fd)


def resize_terminal(fd, rows, cols):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def modify_terminal(fd, tc_attrs, when=termios.TCSANOW):
    return
    IFLAG = 0
    OFLAG = 1
    CFLAG = 2
    LFLAG = 3
    ISPEED = 4
    OSPEED = 5
    CC = 6
    tc_attrs = tc_attrs[:]
    current_attrs = termios.tcgetattr(fd)
    tc_attrs[CC] = current_attrs[termios.CC]
    termios.tcsetattr(fd, when, tc_attrs)


@contextmanager
def open_pty():
    master_fd, slave_fd = pty.openpty()
    try:
        yield master_fd, slave_fd
    finally:
        with ignore_signal(signal.SIGHUP):
            os.close(master_fd)
            os.close(slave_fd)


def print_to_ctty(string):
    """ If there is a ctty, print the given string to it. """
    ctty_fd = get_ctty_fd()
    if ctty_fd is not None:
        print(string, file=os.fdopen(ctty_fd, 'w'))
