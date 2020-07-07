import pickle
import select
import fcntl
import os
import struct
from contextlib import contextmanager
from io import BytesIO

from madbg.utils import loop_in_thread, opposite_dict

MESSAGE_LENGTH_FMT = 'I'


def set_nonblocking(fd):
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def blocking_read(fd, n):
    io = BytesIO()
    read_amount = 0
    while read_amount < n:
        data = os.read(fd, n - read_amount)
        if not data:
            raise IOError('FD closed before all bytes read')
        read_amount += len(data)
        io.write(data)
    return io.getvalue()


def pipe_once(pipe_dict):
    # If read fails, write will fail. But if write fail, we might be still able to read.
    # TODO: use wakeup fd instead of 0 timeout polling (os.pipe? eventfd?)
    # TODO: can use splice or ebpf
    if not pipe_dict:
        return
    reverse_pipe_dict = opposite_dict(pipe_dict)
    for read_fd in select.select(list(pipe_dict), [], [], 0)[0]:
        write_fd = pipe_dict[read_fd]
        try:
            data = os.read(read_fd, 1024)
            if not data:
                raise OSError('EOF')
        except OSError:
            pipe_dict.pop(read_fd, None)
            for writing_fd in reverse_pipe_dict[read_fd]:
                pipe_dict.pop(writing_fd, None)
        else:
            try:
                os.write(write_fd, data)
            except OSError:
                pipe_dict.pop(read_fd, None)


@contextmanager
def pipe_in_background(pipe_dict):
    pipe_dict = dict(pipe_dict)
    with loop_in_thread(pipe_once, pipe_dict):
        yield


def pipe_until_closed(pipe_dict):
    pipe_dict = dict(pipe_dict)
    while pipe_dict:
        pipe_once(pipe_dict)


def send_message(sock, obj):
    message = pickle.dumps(obj)
    message_len = struct.pack(MESSAGE_LENGTH_FMT, len(message))
    sock.sendall(message_len)
    sock.sendall(message)


def receive_message(sock):
    len_len = struct.calcsize(MESSAGE_LENGTH_FMT)
    len_bytes = blocking_read(sock, len_len)
    message_len = struct.unpack(MESSAGE_LENGTH_FMT, len_bytes)[0]
    message = blocking_read(sock, message_len)
    return pickle.loads(message)
