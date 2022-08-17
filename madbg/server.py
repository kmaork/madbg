import os
import pickle
import signal
import struct
import threading
from asyncio import Protocol, StreamReader, StreamWriter, AbstractEventLoop, start_server, new_event_loop, \
    get_event_loop
from concurrent.futures import Future
from threading import RLock, Thread
from typing import Any

from .inject_into_main_thread import prepare_injection, inject
from .consts import DEFAULT_ADDR, Addr
from .debugger import RemoteIPythonDebugger
from .tty_utils import print_to_ctty
from .communication import MESSAGE_LENGTH_FMT, MESSAGE_LENGTH_LENGTH
from .utils import Handlers

CTRL_D = bytes([4])
CTRL_Z = ...
CTRL_BACKSLASH = bytes([28])
CTRL_Q = ...

# TODO: is the correct thing to do is to have multiple PTYs? Then each client could have its
#       own terminal size and type... This doesn't go hand in hand with the current IPythonDebugger
#       design, as it assumes it is singletonic, and it has one output PTY.

class ClientMulticastProtocol(Protocol):
    def __init__(self, loop: AbstractEventLoop):
        self.loop = loop
        self.clients = []

    def add_client(self, client: StreamWriter):
        self.clients.append(client)

    def data_received(self, data: bytes) -> None:
        for client in self.clients:
            client.write(data)
            self.loop.create_task(client.drain())


class Locked:
    def __init__(self, value: Any, lock: RLock = None):
        if lock is None:
            lock = RLock()
        self._value = value
        self._lock = lock

    def set(self, new_val: Any):
        with self:
            self._value = new_val

    # TODO: make generic
    def __enter__(self):
        self._lock.acquire()
        return self._value

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()


class DebuggerServer:
    CHUNK_SIZE = 2 ** 12
    STATE = Locked(None)
    KEY_HANDLERS = Handlers()

    def __init__(self, debugger: RemoteIPythonDebugger, master_writer_stream: StreamWriter,
                 client_multicast: ClientMulticastProtocol):
        self.debugger = debugger
        self.master_writer_stream = master_writer_stream
        self.client_multicast = client_multicast


    @KEY_HANDLERS.register(CTRL_BACKSLASH)
    def ctrl_pipe_handler(self, _key):
        print('yououo')

    def _handle_keys(self, data: bytes) -> bytes:
        for key, handler in self.KEY_HANDLERS:
            if key in data:
                data = data.replace(key, b'')
                handler(key)
        return data

    async def _client_connected(self, reader: StreamReader, writer: StreamWriter):
        self.client_multicast.add_client(writer)
        peer = writer.get_extra_info('peername')
        print_to_ctty(f'Debugger client connected from {peer}')
        config_len = struct.unpack(MESSAGE_LENGTH_FMT, await reader.readexactly(MESSAGE_LENGTH_LENGTH))[0]
        config = pickle.loads(await reader.readexactly(config_len))
        # TODO: make thread safe
        self.debugger.notify_client_connect(config)
        # TODO: only if not tracing already
        inject()
        while not reader.at_eof():
            data = self._handle_keys(await reader.read(self.CHUNK_SIZE))
            self.master_writer_stream.write(data)
            # await self.master_writer_stream.drain()
        self.debugger.notify_client_disconnect()
        # TODO: close writer/reader when done?

    async def _serve(self, addr: Any):
        assert isinstance(addr, tuple) and isinstance(addr[0], str) and isinstance(addr[1], int)
        ip, port = addr
        print_to_ctty(f'Listening for debugger clients on {ip}:{port}')
        server = await start_server(self._client_connected, ip, port)
        await server.serve_forever()

    @classmethod
    async def _async_run(cls, addr: Any, debugger: RemoteIPythonDebugger):
        loop = get_event_loop()
        master_reader = os.fdopen(debugger.pty.master_fd, 'rb')
        master_writer = os.fdopen(debugger.pty.master_fd, 'wb')
        client_multicast = ClientMulticastProtocol(loop)
        await loop.connect_read_pipe(lambda: client_multicast, master_reader)
        write_transport, write_protocol = await loop.connect_write_pipe(Protocol, master_writer)
        master_writer_stream = StreamWriter(write_transport, write_protocol, None, loop)
        self = cls(debugger, master_writer_stream, client_multicast)
        try:
            await self._serve(addr)
        except Exception as e:
            with cls.STATE as state:
                state.set_exception(e)
            raise

    @classmethod
    def _run(cls, addr: Any, debugger: RemoteIPythonDebugger):
        # TODO: Is that right? Not get_event_loop?
        new_event_loop().run_until_complete(cls._async_run(addr, debugger))

    @classmethod
    def make_sure_listening_at(cls, addr: Addr):
        with cls.STATE as state:
            if state is None:
                # TODO: receive addr as arg
                cls.STATE.set(Future())
                prepare_injection()
                Thread(daemon=True, target=cls._run, args=(DEFAULT_ADDR, RemoteIPythonDebugger())).start()
            elif state.done():
                # Raise the exception
                state.result()


"""
- There is only one debugger with one session
- A trace can start at any thread because of a set_trace(), or a client setting it
- A trace can start when there is no client connected, but should print a warning to tty
- A client can disconnect when there is an active trace, but should be warned
- madbg.listen() can tell the server where to accept connections. It adds them to the current session
- when a new client connects, they have a set of options
    - ctrl-p starts snooping stdios (sent by default)
    - ctrl-c stops the program with a breakpoint (sent by default? what if we want a different thread?)
    - ctrl-o stops snooping
    - ctrl-t choose thread
    - ctrl-d stops the tracing
    - ctrl-z detach, asking server to close socket (warning if a trace is still ongoing)
    - ctrl-q client side force-close

Should probably stop using SIGIO, we don't want to disturb the main thread. Just create a daemon thread.
Stop using ThreadPoolExecutor for piping, but instead a daemon thread (how should handle exceptions? maybe signal to main thread? Or just print?)
The debugger it server-independent. It can be instantiated without any client - just a pty.
It's master fd is public, and a server (singleton as well) can read and write into that master fd.
The server filters ctrl-X commands (and maybe other stuff?) before passing it to the debugger.
The server can set_trace on the main thread by using a signal. Sigint should be used.

Bug in pdb - if we are in a PEP475 function, ctrl c runs the siginthandler. But then the syscall
is resumed, and no python code is run. When the user presses ctrl-c again, the handler runs again,
but this time it invokes the debugger... Pdb doesn't allow us to send a sigint here.
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
