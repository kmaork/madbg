import pickle
import select
import fcntl
import os
import struct
from collections import defaultdict
from io import BytesIO

MESSAGE_LENGTH_FMT = 'I'


# TODO: support ssl

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
    """ Pass data between the fds until at least on of each fd pair is closed. """
    # TODO: WTF
    pipe_dict = dict(pipe_dict)
    reverse_pipe_dict = defaultdict(list)
    for k, v in pipe_dict.items():
        reverse_pipe_dict[v].append(k)
    for fd in pipe_dict:
        set_nonblocking(fd)  # TODO: just assert non blocking
    invalid_fds = []
    while pipe_dict:
        for fd in (*pipe_dict.keys(), *pipe_dict.values()):
            try:
                os.fstat(fd)
            except OSError:
                invalid_fds.append(fd)
                try:
                    if fd in pipe_dict:
                        os.write(pipe_dict[fd], os.read(fd, 1024))
                except OSError:
                    pass
        for fd in invalid_fds:
            pipe_dict.pop(fd, None)
            for writing_fd in reverse_pipe_dict[fd]:
                pipe_dict.pop(writing_fd, None)
        invalid_fds = []
        readable_fds, _, _ = select.select(list(pipe_dict), [], [], 0.1)
        for fd in readable_fds:
            try:
                data = os.read(fd, 1024)
            except OSError:
                invalid_fds.append(pipe_dict[fd])
            else:
                if not data:
                    invalid_fds.append(fd)
                try:
                    os.write(pipe_dict[fd], data)
                except OSError:
                    invalid_fds.append(pipe_dict[fd])


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
