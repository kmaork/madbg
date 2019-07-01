import os
import pty
import struct
from contextlib import contextmanager
from multiprocessing.pool import Pool
import signal
import fcntl
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


def detach_ctty(fd):
    fcntl.ioctl(fd, termios.TIOCNOTTY)


def attach_ctty(fd):
    fcntl.ioctl(fd, termios.TIOCSCTTY, 1)  # TODO: what is the 1?


@contextmanager
def set_ctty(fd):
    orig_ctty = os.open('/dev/tty', os.O_RDWR)  # TODO: use os.getttyname, and handle case when there is none
    if not is_session_leader():
        make_session_leader()
    attach_ctty(fd)
    try:
        yield
    finally:
        # TODO: are we attached to a tty originally? because bash is in a different process group,
        # and it is probably attached, so does it mean we aren't? if we are, we should reattach

        # When a process detaches from a tty, it is sent the signals SIGHUP and then SIGCONT
        signal.signal(signal.SIGHUP, lambda *a: None)  # TODO: also sigcont?  # TODO: restore original handler
        detach_ctty(fd)
        os.close(orig_ctty)


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
        os.close(master_fd)
        os.close(slave_fd)