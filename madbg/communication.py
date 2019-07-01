import pickle
import select
import fcntl
import os
import struct
from io import BytesIO

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


def pipe(pipe_dict):
    """
    Pass data between fds until one of them is closed.
    :param pipe_dict: A dict mapping between source fds and dst fds
    """
    for fd in pipe_dict:
        set_nonblocking(fd)
    we_done = False
    while not we_done:
        r, _, _ = select.select(list(pipe_dict), [], [], 0.1)
        for fh in r:
            data = os.read(fh, 1024)
            if not data:
                we_done = True
            os.write(pipe_dict[fh], data)


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
