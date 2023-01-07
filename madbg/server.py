from __future__ import annotations
from functools import partial

from traceback import format_exc
from contextlib import asynccontextmanager

import pickle
import struct
from asyncio import Protocol, StreamReader, StreamWriter, AbstractEventLoop, start_server, new_event_loop, Future, Event
from dataclasses import dataclass, field
from threading import Thread
from typing import Any, Set

from .consts import Addr
from .debugger import RemoteIPythonDebugger, Client
from .tty_utils import print_to_ctty, PTY, TTYConfig
from .communication import MESSAGE_LENGTH_FMT, MESSAGE_LENGTH_LENGTH, read_into_until_stopped
from .utils import Locked
from .app import create_app


@dataclass
class State:
    address: tuple
    future: Future = field(default_factory=Future)


class ClientMulticastProtocol(Protocol):
    def __init__(self, loop: AbstractEventLoop):
        self.loop: AbstractEventLoop = loop
        self.clients: Set[StreamWriter] = set()

    def add_client(self, client: StreamWriter):
        self.clients.add(client)

    def remove_client(self, client: StreamWriter):
        self.clients.remove(client)

    async def _drain(self, client):
        try:
            await client.drain()
        except ConnectionResetError:
            self.clients.remove(client)

    def data_received(self, data: bytes) -> None:
        to_remove = set()
        for client in self.clients:
            if client.is_closing():
                to_remove.add(client)
            else:
                client.write(data)
                self.loop.create_task(client.drain())
        self.clients -= to_remove


@dataclass
class AsyncPTY:
    loop: AbstractEventLoop
    client_multicast: ClientMulticastProtocol
    master_writer_stream: StreamWriter

    @classmethod
    async def create(cls, loop: AbstractEventLoop, pty: PTY) -> AsyncPTY:
        client_multicast = ClientMulticastProtocol(loop)
        await loop.connect_read_pipe(lambda: client_multicast, pty.master_reader)
        write_transport, write_protocol = await loop.connect_write_pipe(Protocol, pty.master_writer)
        master_writer_stream = StreamWriter(write_transport, write_protocol, None, loop)
        return cls(loop, client_multicast, master_writer_stream)

    @asynccontextmanager
    async def read_into(self, writer: StreamWriter):
        self.client_multicast.add_client(writer)
        try:
            yield
        finally:
            self.client_multicast.remove_client(writer)
            await writer.drain()

    @asynccontextmanager
    async def write_into(self, reader: StreamReader):
        stop = Event()
        task = self.loop.create_task(read_into_until_stopped(reader, self.master_writer_stream, stop))
        try:
            yield
        finally:
            stop.set()
            await task

    @asynccontextmanager
    async def connect(self, reader: StreamReader, writer: StreamWriter):
        async with self.read_into(writer), self.write_into(reader):
            yield


@dataclass
class Session:
    loop: AbstractEventLoop
    debugger: RemoteIPythonDebugger
    async_pty: AsyncPTY

    @classmethod
    async def create(cls, loop: AbstractEventLoop, debugger: RemoteIPythonDebugger) -> Session:
        return cls(loop, debugger, await AsyncPTY.create(loop, debugger.pty))

    async def connect_client(self, reader: StreamReader, writer: StreamWriter, tty_config: TTYConfig):
        async with self.async_pty.connect(reader, writer):
            done = Event()
            client = Client(tty_config, partial(self.loop.call_soon_threadsafe, done.set))
            # TODO: make thread safe
            self.debugger.add_client(client)
            await done.wait()
            self.debugger.remove_client(client)


@dataclass
class DebuggerServer:
    STATE = Locked(None)

    loop: AbstractEventLoop
    sessions: dict[Thread, Session] = field(default_factory=dict)

    async def get_session(self, thread: Thread) -> Session:
        session = self.sessions.get(thread)
        if session is None:
            debugger = RemoteIPythonDebugger.get_instance(thread, self.loop)
            session = self.sessions[thread] = await Session.create(self.loop, debugger)
        return session

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter):
        peer = writer.get_extra_info('peername')
        print_to_ctty(f'Madbg - client connected from {peer}')
        config_len = struct.unpack(MESSAGE_LENGTH_FMT, await reader.readexactly(MESSAGE_LENGTH_LENGTH))[0]
        config: TTYConfig = pickle.loads(await reader.readexactly(config_len))
        # Not using context manager because _UnixWritePipeTransport.__del__ closes its pipe
        pty = PTY.new()
        async_pty = await AsyncPTY.create(self.loop, pty)
        async with async_pty.read_into(writer):
            config.apply(pty.slave_fd)
            while True:
                async with async_pty.write_into(reader):
                    choice = await create_app(pty.slave_reader, pty.slave_writer, config.term_type).run_async()
                if choice is None:
                    break
                session = await self.get_session(choice)
                await session.connect_client(reader, writer, config)
        writer.close()
        print_to_ctty(f'Client disconnected {peer}')

    async def _try_handle_client(self, reader: StreamReader, writer: StreamWriter):
        """
        # TODO
        Tried:

        def exception_handler(loop, context):
            print("exception occured, closing server")
            loop.default_exception_handler(context)
            server.close()
        self.loop.set_exception_handler(exception_handler)

        but it didn't work
        """
        try:
            await self._handle_client(reader, writer)
        except:
            print_to_ctty(f'Madbg - error handling client:\n{format_exc()}')
            raise

    async def _serve(self, addr: Any):
        assert isinstance(addr, tuple) and isinstance(addr[0], str) and isinstance(addr[1], int)
        ip, port = addr
        print_to_ctty(f'Listening for debugger clients on {ip}:{port}')
        server = await start_server(self._try_handle_client, ip, port)
        await server.serve_forever()

    @classmethod
    async def _async_run(cls, loop: AbstractEventLoop, addr: Any):
        self = cls(loop)
        try:
            await self._serve(addr)
        except Exception as e:
            with cls.STATE as state:
                state.set_exception(e)
            print('c')
            raise

    @classmethod
    def _run(cls, addr: Any):
        # TODO: Is that right? Not get_event_loop?
        loop = new_event_loop()
        loop.set_debug(True)
        loop.run_until_complete(cls._async_run(loop, addr))

    @classmethod
    def make_sure_listening_at(cls, addr: Addr):
        with cls.STATE as state:
            if state is None:
                # TODO: receive addr as arg
                cls.STATE.set(State(addr))
                Thread(daemon=True, target=cls._run, args=(addr,)).start()
            elif state.future.done():
                # Raise the exception
                state.future.result()
            else:
                # TODO
                if addr != state.address:
                    raise RuntimeError('No support for double bind')


"""
Attach and quit:

Process ForkPoolWorker-3:
Traceback (most recent call last):
  File "/usr/lib/python3.11/multiprocessing/process.py", line 314, in _bootstrap
    self.run()
  File "/usr/lib/python3.11/multiprocessing/process.py", line 108, in run
    self._target(*self._args, **self._kwargs)
  File "/usr/lib/python3.11/multiprocessing/pool.py", line 125, in worker
    result = (True, func(*args, **kwds))
                    ^^^^^^^^^^^^^^^^^^^
  File "/mnt/c/Users/kmaor/Documents/code/hypno/hypno/hypno.py", line 63, in inject_py
    inject(pid, str(temp.name))
  File "/mnt/c/Users/kmaor/Documents/code/pyinjector/pyinjector/pyinjector.py", line 103, in inject
    return injector.inject(library_path)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/mnt/c/Users/kmaor/Documents/code/pyinjector/pyinjector/pyinjector.py", line 87, in inject
    call_c_func(libinjector.injector_inject, self.injector_p, library_path, pointer(handle))
  File "/mnt/c/Users/kmaor/Documents/code/pyinjector/pyinjector/pyinjector.py", line 62, in call_c_func
    ret = func(*args)
          ^^^^^^^^^^^
KeyboardInterrupt
Segmentation fault

"""
"""
Next steps:
    - sqlite errors
    - when writing ? in the terminal, "Object `` not found." is printed to stdout 
    - run in thread using ptrace - better than signal??
        signal: interfering with signal handlers
        ptrace: invoke subprocess, load dll
            which of them is more reentrant?
            can we at least verify the dest thread is blocked on a syscall? this is probable as we are holding
            the gil.
            do we have another approach?
    - get rid of piping
    - use the new api for setting trace on other threads
    - user connects, gets main app - choose thread to debug
      to users can debug two separate threads at once
      when two users are debugging the same thread:
        double connect?
        decline second user?
      each thread should have only one controller state, therefore one app
      the app could be configured with the first user's terminal, and connected through a raw pty to each
      user's pty
      so each thread has a pty, and each user has a pty
    - app - show periodically updated stack traces
    - deadlock detection support
    - pyinjector issues:
        - getting the python error back to us or at least know that it failed
        - threads
        - deadlock
    - client-level detach (c-z, c-\)
    - support processes without tty
    - support mac n windows


python -c $'import madbg; madbg.start()\nwhile 1: print(__import__("time").sleep(1) or ":)")'
python -c $'while 1: print(__import__("time").sleep(1) or ":)")'

UI
    There are three views:
        1. Main debugger
            - See all threads
            - Choose a thread
            - Quit
        2. Thread view
            - Start debugging
            - See live stack trace
            - Quit
            - Go to main
        3. Debugger
            - Go to thread view (continue)
            - Go to main (quit)
    Local mode:
        madbg run bla
        or madbg.start_here()
        will open the UI in the current terminal


- There is only one debugger with one session
- A trace can start at any thread because of a set_trace(), or a client setting it
- A trace can start when there is no client connected, but should print a warning to tty
- A client can disconnect when there is an active trace, but should be warned
- madbg.listen() can tell the server where to accept connections. It adds them to the current session
- when a new client connects, they have a set of options
    - ctrl-p toggle snooping stdios (on by default)
    - ctrl-c stops the program with a breakpoint (sent by default? what if we want a different thread?)
    - ctrl-t choose thread
    - ctrl-d detach, asking server to close socket (warning if a trace is still ongoing)
    - ctrl-z client size pause
    - ctrl-q client side force-close

Should probably stop using SIGIO, we don't want to disturb the main thread. Just create a daemon thread.
Stop using ThreadPoolExecutor for piping, but instead a daemon thread (how should handle exceptions? maybe signal to main thread? Or just print?)
The debugger it server-independent. It can be instantiated without any client - just a pty.
It's master fd is public, and a server (singleton as well) can read and write into that master fd.
The server filters ctrl-X commands (and maybe other stuff?) before passing it to the debugger.
The server can set_trace on the main thread by using a signal. Sigint should be used.

Bug in pdb - if we are in a PEP475 function, ctrl c runs the siginthandler. But then the syscall
is resumed, and no python code is run. When the user presses ctrl-c again, the handler runs again,
but this time sys.trace is in place so the handler is debugged... Pdb doesn't allow us to send a sigint here.
The solution is probably to somehow prevent tracing of the handler... Doesn't sound simple.

==================
- show some kind of output from the injection process, errors, etc... maybe using a socket?
- madbg attach
	- use /proc/pid/exe to identify the interpreter
	- if --install --pip-args a b c:
		- int -m pip install madbg==our version
		- int -m madbg test (madbg is installed and ready to use!)
	- inejct
	- if not --install and fail:
		- int -m madbg test and offer to run madbg install: "Detected target interpreter (alds) doesn't seems to have madbg installed. Rerun with --install to first install madbg in the target interpreter"

- Fabio Zadrozny
"""
