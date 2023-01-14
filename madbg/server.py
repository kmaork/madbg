from __future__ import annotations
from functools import partial
from prompt_toolkit.application import create_app_session
from concurrent.futures import ThreadPoolExecutor, Future

from traceback import format_exc
from contextlib import asynccontextmanager, AsyncExitStack

import pickle
import struct
from asyncio import Protocol, StreamReader, StreamWriter, AbstractEventLoop, start_server, new_event_loop, \
    Event, Task, CancelledError
from dataclasses import dataclass
from threading import Thread
from typing import Set, Optional

from .consts import Addr
from .debugger import RemoteIPythonDebugger, Client
from .tty_utils import print_to_ctty, PTY, TTYConfig
from .communication import MESSAGE_LENGTH_FMT, MESSAGE_LENGTH_LENGTH, read_into_until_stopped
from .app import create_app


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
    pty: PTY
    client_multicast: ClientMulticastProtocol
    master_writer_stream: StreamWriter

    @classmethod
    @asynccontextmanager
    async def open(cls, loop: AbstractEventLoop) -> AsyncPTY:
        with PTY.open() as pty:
            protocol_factory = partial(ClientMulticastProtocol, loop)
            read_transport, client_multicast = await loop.connect_read_pipe(protocol_factory, pty.master_io)
            write_transport, write_protocol = await loop.connect_write_pipe(Protocol, pty.master_io)
            master_writer_stream = StreamWriter(write_transport, write_protocol, None, loop)
            try:
                yield cls(loop, pty, client_multicast, master_writer_stream)
            finally:
                # Invoke the destructors that close the pipes
                read_transport.close()
                write_transport.close()

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
    @asynccontextmanager
    async def create(cls, loop: AbstractEventLoop, thread: Thread) -> Session:
        async with AsyncPTY.open(loop) as async_pty:
            debugger = RemoteIPythonDebugger(thread, async_pty.pty)
            yield cls(loop, debugger, async_pty)

    async def connect_client(self, reader: StreamReader, writer: StreamWriter, tty_config: TTYConfig):
        async with self.async_pty.connect(reader, writer):
            done = Event()
            client = Client(tty_config, partial(self.loop.call_soon_threadsafe, done.set))
            # TODO: make thread safe
            self.debugger.add_client(client)
            await done.wait()
            self.debugger.remove_client(client)


class DebuggerServer(Thread):
    INSTANCE: Optional[DebuggerServer] = None

    def __init__(self, addr: Addr):
        super().__init__(name='madbg', daemon=True)
        self.addr = addr
        self.loop: AbstractEventLoop = new_event_loop()
        self.sessions: dict[Thread, Session] = {}
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        self.executor: ThreadPoolExecutor = ThreadPoolExecutor(64)
        self.future: Future = Future()
        self.serve_task: Optional[Task] = None

    def __post_init__(self):
        self.exit_stack.push(self.executor)
        self.loop.set_debug(True)

    async def get_session(self, thread: Thread) -> Session:
        session = self.sessions.get(thread)
        if session is None:
            session_cm = Session.create(self.loop, thread)
            session = self.sessions[thread] = await self.exit_stack.enter_async_context(session_cm)
        return session

    def _get_madbg_threads(self):
        threads = {self}
        try:
            with self.executor._shutdown_lock:
                threads.update(self.executor._threads)
        except AttributeError:
            raise
        try:
            for session in self.sessions.values():
                with session.debugger.thread_executor._shutdown_lock:
                    threads.update(session.debugger.thread_executor._threads)
        except AttributeError:
            raise
        try:
            threads.update(s.debugger.shell.history_manager.save_thread for s in self.sessions.values())
        except AttributeError:
            raise
        return threads

    def _run_app(self, async_pty: AsyncPTY, config: TTYConfig) -> Optional[Thread]:
        """
        Without create_app_session we get mixups between different running apps, and only one could run at a time.
        According to prompt_toolkit docs at https://github.com/prompt-toolkit/python-prompt-toolkit/blob/
        6b4af4e1c8763f2f3ccb2938605a44f57a1b8b5f/src/prompt_toolkit/application/application.py#L179:

        (Note that the preferred way to change the input/output is by creating an
        `AppSession` with the required input/output objects. If you need multiple
        applications running at the same time, you have to create a separate
        `AppSession` using a `with create_app_session():` block.
        """
        with create_app_session():
            threads_blacklist = self._get_madbg_threads()
            app = create_app(async_pty.pty.slave_io,
                             async_pty.pty.slave_io,
                             config.term_type,
                             threads_blacklist)

            def on_exit():
                if app.is_running:
                    app.exit()

            self.exit_stack.callback(on_exit)
            return app.run()

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter):
        peer = writer.get_extra_info('peername')
        print_to_ctty(f'Madbg - client connected from {peer}')
        config_len = struct.unpack(MESSAGE_LENGTH_FMT, await reader.readexactly(MESSAGE_LENGTH_LENGTH))[0]
        config: TTYConfig = pickle.loads(await reader.readexactly(config_len))
        # Not using context manager because _UnixWritePipeTransport.__del__ closes its pipe
        async with AsyncPTY.open(self.loop) as async_pty, async_pty.read_into(writer):
            config.apply(async_pty.pty.slave_fd)
            while True:
                async with async_pty.write_into(reader):
                    # Running in executor because of https://github.com/prompt-toolkit/python-prompt-toolkit/issues/1705
                    app = self.loop.run_in_executor(self.executor, self._run_app, async_pty, config)
                    self.exit_stack.push_async_callback(lambda: app)
                    choice = await app
                if choice is None:
                    break
                session = await self.get_session(choice)
                await session.connect_client(reader, writer, config)
        writer.close()
        print_to_ctty(f'Client disconnected {peer}')

    async def _serve(self):
        # TODO: support all addr types
        assert isinstance(self.addr, tuple) and isinstance(self.addr[0], str) and isinstance(self.addr[1], int)
        ip, port = self.addr
        print_to_ctty(f'Listening for debugger clients on {ip}:{port}')
        server = await start_server(self._handle_client, ip, port)
        await server.serve_forever()

    async def _async_run(self):
        self.serve_task = self.loop.create_task(self._serve())
        try:
            await self.serve_task
        except CancelledError:
            pass
        except Exception as e:
            print_to_ctty(f'Madbg - error handling client:\n{format_exc()}')
            self.future.set_exception(e)
            raise
        finally:
            await self.exit_stack.aclose()

    def run(self):
        self.loop.run_until_complete(self._async_run())
        self.future.set_result(None)

    @classmethod
    def make_sure_listening_at(cls, addr: Addr):
        if cls.INSTANCE is None:
            self = cls(addr)
            self.start()
            cls.INSTANCE = self
        else:
            if cls.INSTANCE.future.done():
                # Raise the exception
                cls.INSTANCE.future.result()
                # TODO
                raise RuntimeError('Rerunning the server is not supported yet')
            else:
                if addr != cls.INSTANCE.addr:
                    # TODO
                    raise RuntimeError('Binding on multiple addresses is not supported yet')

    @classmethod
    def stop(cls):
        if cls.INSTANCE is None:
            pass
        else:
            if cls.INSTANCE.future.done():
                # Raise the exception
                cls.INSTANCE.future.result()
                # TODO
                raise RuntimeError()
            else:
                if cls.INSTANCE.serve_task is not None:
                    cls.INSTANCE.loop.call_soon_threadsafe(lambda: cls.INSTANCE.serve_task.cancel())
                # Wait for server to finish
                cls.INSTANCE.future.result()


"""
1! None
1! None
2! <frame at 0x7f178113eca0, file '/mnt/c/Users/kmaor/Documents/code/madbg/scripts/demo.py', line 15, code a>
Hello second thread
Hello second thread
Hello second thread
Hello second thread
1! None
Hello second thread
Traceback (most recent call last):
  File "/mnt/c/Users/kmaor/Documents/code/madbg/scripts/demo.py", line 26, in <module>
    a()
  File "/mnt/c/Users/kmaor/Documents/code/madbg/scripts/demo.py", line 15, in a
    print('Hello main thread')
    ^^^^^
  File "/mnt/c/Users/kmaor/Documents/code/madbg/scripts/demo.py", line 15, in a
    print('Hello main thread')
    ^^^^^
  File "/mnt/c/Users/kmaor/Documents/code/madbg/madbg/debugger.py", line 134, in trace_dispatch
    s = super().trace_dispatch(frame, event, arg)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.11/bdb.py", line 90, in trace_dispatch
    return self.dispatch_line(frame)
           ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.11/bdb.py", line 114, in dispatch_line
    self.user_line(frame)
  File "/usr/lib/python3.11/pdb.py", line 342, in user_line
    self.interaction(frame, None)
  File "/mnt/c/Users/kmaor/Documents/code/clones/ipython/IPython/core/debugger.py", line 335, in interaction
    OldPdb.interaction(self, frame, traceback)
  File "/usr/lib/python3.11/pdb.py", line 437, in interaction
    self._cmdloop()
  File "/usr/lib/python3.11/pdb.py", line 402, in _cmdloop
    self.cmdloop()
  File "/mnt/c/Users/kmaor/Documents/code/clones/ipython/IPython/terminal/debugger.py", line 139, in cmdloop
    self._ptcomp.ipy_completer.global_namespace = self.curframe.f_globals
                                                  ^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'f_globals'

attached mainthread and pressed enter
"""


"""
Next steps:
    - self.curframe is none bug
    - after debugging for a while, needed to quit multiple times to get out
    - release pyinjector and hypno versions
    - after debugger is conncted, need two c-c:
        we can't just make those threads daemons, we want cleanup code to run
        we want to cancel all apps and wait for them
    - client cleanup doesn't completely reset terminal, when app exits not clean, client terminal is dead
    - ipython prs - do we need to patch? or maybe depend on a fork?
    - trying to attach to two threads in parallel (two threads asleep, c-c to both) - one gets stuck.
    - our own executors are showing up in the menu, hide them by keeping a list of them
    - skip menu if there is only one thread?
    - when writing ? in the terminal, "Object `` not found." is printed to stdout 
    - once we set trace on a thread, maybe during continue we don't cancel the trace but just don't invoke the debugger,
      then we don't have to reattach the thread
    - run in thread using ptrace - better than signal??
        signal: interfering with signal handlers
        ptrace: invoke subprocess, load dll
            which of them is more reentrant?
            can we at least verify the dest thread is blocked on a syscall? this is probable as we are holding
            the gil.
            do we have another approach?
    - get rid of piping
    - signal.siginterrupt - use to attach to threads in syscalls?
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


UI
    There are three views:
        1. Main debugger
            - See all threads
            - Choose a thread
            - Quit
        2. Thread view
            - Start debugging
            - See live stack trace and locals
                - live could be implemented by polling or by putting weakrefs on thread frames and using callbacks
                  to update
                - use color to represent freshness of frames so it'll be clear what threads are stuck
                - deadlock detection:
                    - can we find out all threads stuck on an acquire call and tell who acquired the locks?
                        possible for rlocks, not for locks - might need pthread/kernel level data for that.
                    - after we found the deadlock, we can try and point out the bad code by traveling the stack and looking for withs
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
