from __future__ import annotations
import os
import struct
from collections import defaultdict
from functools import partial
from asyncio import new_event_loop
from typing import Dict, Set, Optional

MESSAGE_LENGTH_FMT = 'I'
MESSAGE_LENGTH_LENGTH = struct.calcsize(MESSAGE_LENGTH_FMT)

PipeDict = Dict[int, Set[int]]


class Piping:
    # TODO: remove this class and replace with a protocol
    def __init__(self, pipe_dict: Optional[PipeDict] = None):
        super().__init__()
        self.buffers = defaultdict(bytes)
        self.loop = new_event_loop()
        self.readers_to_writers = defaultdict(set)
        self.writers_to_readers = defaultdict(set)
        if pipe_dict is not None:
            self.add_pipe(pipe_dict)

    def add_pair(self, reader_fd: int, writer_fd: int):
        if reader_fd not in self.readers_to_writers:
            self.loop.add_reader(reader_fd, partial(self._read, reader_fd))
        if writer_fd not in self.writers_to_readers:
            self.loop.add_writer(writer_fd, partial(self._write, writer_fd))
        self.readers_to_writers[reader_fd].add(writer_fd)
        self.writers_to_readers[writer_fd].add(reader_fd)

    def add_pipe(self, pipe_dict: PipeDict):
        for reader_fd, writer_fds in pipe_dict.items():
            for writer_fd in writer_fds:
                self.add_pair(reader_fd, writer_fd)

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

    def _write(self, dest_fd):
        buffer = self.buffers[dest_fd]
        if buffer:
            self.buffers[dest_fd] = buffer[os.write(dest_fd, buffer):]

    def run(self):
        self.loop.run_forever()
