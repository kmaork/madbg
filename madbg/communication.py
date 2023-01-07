from __future__ import annotations

from contextlib import asynccontextmanager

import os
import struct
from collections import defaultdict
from asyncio import new_event_loop, StreamReader, wait, FIRST_COMPLETED, Event, get_running_loop
from typing import Dict, Set, Optional

MESSAGE_LENGTH_FMT = 'I'
MESSAGE_LENGTH_LENGTH = struct.calcsize(MESSAGE_LENGTH_FMT)
CHUNK_SIZE = 2 ** 12

PipeDict = Dict[int, Set[int]]


async def read_into(reader: StreamReader, writer_fd: int, chunk_size=CHUNK_SIZE):
    while True:
        if reader.at_eof():
            break
        data = await reader.read(chunk_size)
        # TODO: Use async mechanism to make sure all data is written
        os.write(writer_fd, data)


async def read_into_until_stopped(reader: StreamReader, writer_fd: int, done: Event):
    loop = get_running_loop()
    done_task = loop.create_task(done.wait())
    read_task = loop.create_task(read_into(reader, writer_fd))
    finished, unfinished = await wait([done_task, read_task], return_when=FIRST_COMPLETED)
    if done_task in finished:
        for task in unfinished:
            task.cancel()


@asynccontextmanager
async def context_read_into(reader: StreamReader, writer_fd: int):
    stop = Event()
    task = get_running_loop().create_task(read_into_until_stopped(reader, writer_fd, stop))
    try:
        yield
    finally:
        stop.set()
        await task


def read_new_data(fd: int, chunk_size=CHUNK_SIZE) -> bytearray:
    data = bytearray()
    try:
        while not data:
            new_data = os.read(fd, chunk_size)
            if not new_data:
                break
            data.extend(new_data)
    except OSError:
        pass
    return data


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
            self.loop.add_reader(reader_fd, self._read, reader_fd)
        if writer_fd not in self.writers_to_readers:
            self.loop.add_writer(writer_fd, self._write, writer_fd)
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
        data = read_new_data(src_fd)
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
