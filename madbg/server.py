import os
import pickle
import struct
from asyncio import Protocol, StreamReader, StreamWriter, BaseEventLoop, get_event_loop, start_server
from typing import Any

from .debugger import RemoteIPythonDebugger
from .tty_utils import print_to_ctty
from .utils import Singleton
from .communication import MESSAGE_LENGTH_FMT, MESSAGE_LENGTH_LENGTH


# TODO: is the correct thing to do is to have multiple PTYs? Then each client could have its
#       own terminal size and type... This doesn't go hand in hand with the current IPythonDebugger
#       design, as it assumes it is singletonic, and it has one output PTY.


class ClientMulticastProtocol(Protocol):
    def __init__(self, loop: BaseEventLoop):
        self.loop = loop
        self.clients = []

    def add_client(self, client: StreamWriter):
        self.clients.append(client)

    def data_received(self, data: bytes) -> None:
        for client in self.clients:
            client.write(data)
            self.loop.create_task(client.drain())


class DebuggerServer(metaclass=Singleton):
    CHUNK_SIZE = 2 ** 12

    def __init__(self, debugger: RemoteIPythonDebugger, master_writer_stream: StreamWriter,
                 client_multicast: ClientMulticastProtocol):
        self.debugger = debugger
        self.master_writer_stream = master_writer_stream
        self.client_multicast = client_multicast

    async def _client_connected(self, reader: StreamReader, writer: StreamWriter):
        self.client_multicast.add_client(writer)
        peer = writer.get_extra_info('peername')
        print_to_ctty(f'Debugger client connected from {peer}')
        config_len = struct.unpack(MESSAGE_LENGTH_FMT, await reader.readexactly(MESSAGE_LENGTH_LENGTH))[0]
        config = pickle.loads(await reader.readexactly(config_len))
        self.debugger.notify_client_connect(config)
        while not reader.at_eof():
            data = await reader.read(self.CHUNK_SIZE)
            self.master_writer_stream.write(data)
            await self.master_writer_stream.drain()
        self.debugger.notify_client_disconnect()

    async def serve(self, addr: Any):
        assert isinstance(addr, tuple) and isinstance(addr[0], str) and isinstance(addr[1], int)
        ip, port = addr
        print_to_ctty(f'Listening for debugger clients on {ip}:{port}')
        await start_server(self._client_connected, ip, port)

    @classmethod
    def run(cls, addr: Any, loop: BaseEventLoop = None, debugger: RemoteIPythonDebugger = None):
        if loop is None:
            loop = get_event_loop()
        if debugger is None:
            debugger = RemoteIPythonDebugger()
        master_reader = os.fdopen(debugger.pty.master_fd, 'rb')
        master_writer = os.fdopen(debugger.pty.master_fd, 'wb')
        client_multicast = ClientMulticastProtocol(loop)
        loop.connect_read_pipe(lambda: client_multicast, master_reader)
        write_transport, write_protocol = loop.connect_write_pipe(Protocol, master_writer)
        master_writer_stream = StreamWriter(write_transport, write_protocol, None, loop)
        self = cls(debugger, master_writer_stream, client_multicast)
        loop.run_until_complete(self.serve(addr))


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
"""
