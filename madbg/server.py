import os
import pickle
import struct
import threading
from asyncio import Protocol, StreamReader, StreamWriter, AbstractEventLoop, start_server, new_event_loop, Future
from dataclasses import dataclass, field
from threading import Thread
from typing import Any, Set

from .consts import Addr
from .debugger import RemoteIPythonDebugger
from .tty_utils import print_to_ctty
from .communication import MESSAGE_LENGTH_FMT, MESSAGE_LENGTH_LENGTH
from .utils import Locked
from .app import create

CTRL_D = bytes([4])
CHUNK_SIZE = 2 ** 12


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
class Session:
    loop: AbstractEventLoop
    debugger: RemoteIPythonDebugger
    client_multicast: ClientMulticastProtocol
    master_writer_stream: StreamWriter

    @classmethod
    async def create(cls, loop: AbstractEventLoop, debugger: RemoteIPythonDebugger):
        master_reader = os.fdopen(debugger.pty.master_fd, 'rb')
        master_writer = os.fdopen(debugger.pty.master_fd, 'wb')
        client_multicast = ClientMulticastProtocol(loop)
        await loop.connect_read_pipe(lambda: client_multicast, master_reader)
        write_transport, write_protocol = await loop.connect_write_pipe(Protocol, master_writer)
        master_writer_stream = StreamWriter(write_transport, write_protocol, None, loop)
        return cls(loop, debugger, client_multicast, master_writer_stream)

    async def connect_client(self, reader: StreamReader, writer: StreamWriter):
        self.client_multicast.add_client(writer)
        peer = writer.get_extra_info('peername')
        print_to_ctty(f'Debugger client connected from {peer}')
        config_len = struct.unpack(MESSAGE_LENGTH_FMT, await reader.readexactly(MESSAGE_LENGTH_LENGTH))[0]
        config = pickle.loads(await reader.readexactly(config_len))
        # TODO: make thread safe
        self.debugger.notify_client_connect(config)

        @self.debugger.done_callbacks.add
        def one_debugger_done():
            self.loop.call_soon_threadsafe(reader.feed_eof)

        while not reader.at_eof():
            data = await reader.read(CHUNK_SIZE)
            detach_cmd_i = data.find(CTRL_D)
            if detach_cmd_i != -1:
                data = data[:detach_cmd_i]
            self.master_writer_stream.write(data)
            # TODO: what?
            # loop.create_task(self.master_writer_stream.drain())
            if detach_cmd_i != -1:
                writer.write(b'\r\nDetaching\r\n')
                break
        writer.close()
        print_to_ctty(f'Client disconnected {peer}')
        self.debugger.notify_client_disconnect()
        self.client_multicast.remove_client(writer)


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

    async def _client_connected(self, reader: StreamReader, writer: StreamWriter):
        session = await self.get_session(threading.main_thread())
        await session.connect_client(reader, writer)

    async def _serve(self, addr: Any):
        assert isinstance(addr, tuple) and isinstance(addr[0], str) and isinstance(addr[1], int)
        ip, port = addr
        print_to_ctty(f'Listening for debugger clients on {ip}:{port}')
        server = await start_server(self._client_connected, ip, port)
        await server.serve_forever()

    @classmethod
    async def _async_run(cls, loop: AbstractEventLoop, addr: Any):
        self = cls(loop)
        try:
            await self._serve(addr)
        except Exception as e:
            with cls.STATE as state:
                state.set_exception(e)
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
                if addr != state.address:
                    # TODO
                    raise RuntimeError('No support for double bind')


"""
app - show periodically updated stack traces
deadlock detection support

Next steps:
    - revert safe injection diff in hypno
    - when writing ? in the terminal, "Object `` not found." is printed to stdout 
    - no \r printed...
    - continue raises exceptions
    - run in thread using ptrace - better than signal??
        signal: interfering with signal handlers
        ptrace: invoke subprocess, load dll
            which of them is more reentrant?
            can we at least verify the dest thread is blocked on a syscall? this is probable as we are holding
            the gil.
            do we have another approach?
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
    - pyinjector issues:
        - getting the python error back to us or at least know that it failed
        - threads
        - deadlock
    - client-level detach (c-z, c-\)
    - support processes without tty
    - support mac n windows


python -c $'import madbg; madbg.start()\nwhile 1: print(__import__("time").sleep(1) or ":)")'
python -c $'while 1: print(__import__("time").sleep(1) or ":)")'
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
