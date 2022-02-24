from __future__ import annotations
import pickle
import fcntl
import os
import struct
from collections import defaultdict
from functools import partial, wraps
from asyncio import new_event_loop
from io import BytesIO
from threading import RLock
from typing import Dict, Set, Any, Callable, Optional, Iterable

MESSAGE_LENGTH_FMT = 'I'

PipeDict = Dict[int, Set[int]]


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


class Locked:
    def __init__(self):
        self.lock = RLock()

    @classmethod
    def thread_safe(cls, method: Callable[[Locked, ...], Any]):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            with self.lock:
                return method(self, *args, **kwargs)

        return wrapper


class Piping(Locked):
    def __init__(self, pipe_dict: Optional[PipeDict] = None):
        super().__init__()
        self.buffers = defaultdict(bytes)
        self.loop = new_event_loop()
        self.readers_to_writers = defaultdict(set)
        self.writers_to_readers = defaultdict(set)
        if pipe_dict is not None:
            self.add_pipe(pipe_dict)

    @Locked.thread_safe
    def add_pair(self, reader_fd: int, writer_fd: int):
        if reader_fd not in self.readers_to_writers:
            self.loop.add_reader(reader_fd, partial(self._read, reader_fd))
        if writer_fd not in self.writers_to_readers:
            self.loop.add_writer(writer_fd, partial(self._write, writer_fd))
        self.readers_to_writers[reader_fd].add(writer_fd)
        self.writers_to_readers[writer_fd].add(reader_fd)

    @Locked.thread_safe
    def add_pipe(self, pipe_dict: PipeDict):
        for reader_fd, writer_fds in pipe_dict.items():
            for writer_fd in writer_fds:
                self.add_pair(reader_fd, writer_fd)

    @Locked.thread_safe
    def _remove_writer(self, writer_fd):
        self.loop.remove_writer(writer_fd)
        for reader_fd in self.writers_to_readers.pop(writer_fd):
            self.readers_to_writers.pop(reader_fd)

    @Locked.thread_safe
    def _remove_reader(self, reader_fd):
        # remove all writers that im the last to write to, remove all that write to me, if nothing left stop loop
        self.loop.remove_reader(reader_fd)
        writer_fds = self.readers_to_writers.pop(reader_fd)
        for writer_fd in writer_fds:
            writer_readers = self.writers_to_readers[writer_fd]
            writer_readers.remove(reader_fd)
            if not writer_readers:
                self._remove_writer(writer_fd)

    @Locked.thread_safe
    def _read(self, src_fd):
        try:
            data = os.read(src_fd, 1024)
        except OSError:
            data = ''
        if data:
            for dest_fd in self.readers_to_writers[src_fd]:
                self.buffers[dest_fd] += data
        else:
            self._remove_reader(src_fd)
            if src_fd in self.writers_to_readers:
                self._remove_writer(src_fd)
            if not self.readers_to_writers:
                self.loop.stop()

    @Locked.thread_safe
    def _write(self, dest_fd):
        buffer = self.buffers[dest_fd]
        if buffer:
            self.buffers[dest_fd] = buffer[os.write(dest_fd, buffer):]

    @Locked.thread_safe
    def run(self):
        self.loop.run_forever()
        # TODO: is this needed?
        # for dest_fd, buffer in self.buffers.items():
        #     while buffer:
        #         buffer = buffer[os.write(dest_fd, buffer):]


class Session:
    def __init__(self, master_fd: int, clients: Iterable[int]):
        self.master_fd = master_fd
        self.piping = Piping()
        for client in clients:
            self.connect_client(client)

    def connect_client(self, fd: int):
        self.piping.add_pipe({fd: {self.master_fd}, self.master_fd: {fd}})

    def run(self):
        self.piping.run()


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
