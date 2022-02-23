import pickle
import fcntl
import os
import struct
from collections import defaultdict
from functools import partial
from asyncio import new_event_loop
from io import BytesIO
from typing import Dict, Set

from .utils import opposite_dict

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


class Piping:
    def __init__(self, pipe_dict: Dict[int, Set[int]]):
        self.buffers = defaultdict(bytes)
        self.loop = new_event_loop()
        for src_fd, dest_fds in pipe_dict.items():
            self.loop.add_reader(src_fd, partial(self._read, src_fd, dest_fds))
            for dest_fd in dest_fds:
                self.loop.add_writer(dest_fd, partial(self._write, dest_fd))
        self.readers_to_writers = dict(pipe_dict)
        self.writers_to_readers = opposite_dict(pipe_dict)

    def _remove_writer(self, writer_fd):
        self.loop.remove_writer(writer_fd)
        for reader_fd in self.writers_to_readers.pop(writer_fd):
            self.readers_to_writers.pop(reader_fd)

    def _remove_reader(self, reader_fd):
        # remove all writers that im the last to write to, remove all that write to me, if nothing left stop loop
        self.loop.remove_reader(reader_fd)
        writer_fds = self.readers_to_writers.pop(reader_fd)
        for writer_fd in writer_fds:
            writer_readers = self.writers_to_readers[writer_fd]
            writer_readers.remove(reader_fd)
            if not writer_readers:
                self._remove_writer(writer_fd)

    def _read(self, src_fd, dest_fds):
        try:
            data = os.read(src_fd, 1024)
        except OSError:
            data = ''
        if data:
            for dest_fd in dest_fds:
                self.buffers[dest_fd] += data
        else:
            self._remove_reader(src_fd)
            if src_fd in self.writers_to_readers:
                self._remove_writer(src_fd)
            if not self.readers_to_writers:
                self.loop.stop()

    def _write(self, dest_fd):
        buffer = self.buffers[dest_fd]
        if buffer:
            self.buffers[dest_fd] = buffer[os.write(dest_fd, buffer):]

    def run(self):
        self.loop.run_forever()
        # TODO: is this needed?
        # for dest_fd, buffer in self.buffers.items():
        #     while buffer:
        #         buffer = buffer[os.write(dest_fd, buffer):]


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
