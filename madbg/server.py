from __future__ import annotations
from functools import partial
from prompt_toolkit.application import Application, create_app_session
from concurrent.futures import ThreadPoolExecutor, Future

from traceback import format_exc
from contextlib import asynccontextmanager, AsyncExitStack
import atexit
import threading
import pickle
import struct
from asyncio import Protocol, StreamReader, StreamWriter, AbstractEventLoop, start_server, new_event_loop, \
    Event, Task, Lock, CancelledError, run_coroutine_threadsafe, current_task, wait, FIRST_COMPLETED
from dataclasses import dataclass
from threading import Thread
from typing import Set, Optional

from .consts import Addr
from .debugger import RemoteIPythonDebugger, Client, exit_app
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

    def data_received(self, data: bytes) -> None:
        to_remove = set()
        for client in self.clients:
            if client.is_closing():
                to_remove.add(client)
            else:
                # No drain: the transport buffers, and a fire-and-forget drain task can only fail unobserved
                client.write(data)
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
            yield task
        finally:
            stop.set()
            await task

    @asynccontextmanager
    async def connect(self, reader: StreamReader, writer: StreamWriter):
        async with self.read_into(writer), self.write_into(reader) as write_task:
            yield write_task


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
        async with self.async_pty.connect(reader, writer) as write_task:
            done = Event()
            client = Client(tty_config, partial(self.loop.call_soon_threadsafe, done.set))
            self.debugger.add_client(client)
            done_task = self.loop.create_task(done.wait())
            try:
                # The write task finishes when the client disconnects
                await wait([done_task, write_task], return_when=FIRST_COMPLETED)
            finally:
                done_task.cancel()
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
        self.client_tasks: Set[Task] = set()
        self.sessions_lock = Lock()
        self.exit_stack.push(self.executor)

    async def get_session(self, thread: Thread) -> Session:
        # Locking so two callers don't create two sessions for the same thread
        async with self.sessions_lock:
            session = self.sessions.get(thread)
            if session is None:
                session_cm = Session.create(self.loop, thread)
                session = self.sessions[thread] = await self.exit_stack.enter_async_context(session_cm)
        return session

    def get_debugger(self, thread: Thread) -> RemoteIPythonDebugger:
        """ Thread-safe way to get the debugger of the given thread, to be called from outside the server's thread """
        return run_coroutine_threadsafe(self.get_session(thread), self.loop).result().debugger

    def _get_madbg_threads(self):
        threads = {self}
        with self.executor._shutdown_lock:
            threads.update(self.executor._threads)
        for session in self.sessions.values():
            with session.debugger.thread_executor._shutdown_lock:
                threads.update(session.debugger.thread_executor._threads)
        threads.update(s.debugger.shell.history_manager.save_thread for s in self.sessions.values())
        return threads

    @staticmethod
    def _run_app(app: Application, stop: threading.Event) -> Optional[Thread]:
        """
        Without create_app_session we get mixups between different running apps, and only one could run at a time.
        According to prompt_toolkit docs at https://github.com/prompt-toolkit/python-prompt-toolkit/blob/
        6b4af4e1c8763f2f3ccb2938605a44f57a1b8b5f/src/prompt_toolkit/application/application.py#L179:

        (Note that the preferred way to change the input/output is by creating an
        `AppSession` with the required input/output objects. If you need multiple
        applications running at the same time, you have to create a separate
        `AppSession` using a `with create_app_session():` block.
        """
        def exit_if_stopped():
            # Exiting an app that didn't start yet is a no-op
            if stop.is_set():
                app.exit()

        with create_app_session():
            return app.run(pre_run=exit_if_stopped)

    async def _choose_thread(self, async_pty: AsyncPTY, reader: StreamReader, config: TTYConfig) -> Optional[Thread]:
        """ Show the thread menu until the client chooses a thread, exits, or disconnects """
        app = create_app(async_pty.pty.slave_io, async_pty.pty.slave_io, config.term_type, self._get_madbg_threads())
        stop = threading.Event()
        try:
            async with async_pty.write_into(reader) as write_task:
                # Running in executor because of https://github.com/prompt-toolkit/python-prompt-toolkit/issues/1705
                app_future = self.loop.run_in_executor(self.executor, self._run_app, app, stop)
                # The write task finishes when the client disconnects
                await wait([app_future, write_task], return_when=FIRST_COMPLETED)
                if app_future.done():
                    return app_future.result()
        finally:
            stop.set()
            exit_app(app)

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter):
        try:
            peer = writer.get_extra_info('peername')
            print_to_ctty(f'Madbg - client connected from {peer}')
            config_len = struct.unpack(MESSAGE_LENGTH_FMT, await reader.readexactly(MESSAGE_LENGTH_LENGTH))[0]
            config: TTYConfig = pickle.loads(await reader.readexactly(config_len))
            # Not using context manager because _UnixWritePipeTransport.__del__ closes its pipe
            async with AsyncPTY.open(self.loop) as async_pty, async_pty.read_into(writer):
                config.apply(async_pty.pty.slave_fd)
                while True:
                    choice = await self._choose_thread(async_pty, reader, config)
                    if choice is None:
                        break
                    session = await self.get_session(choice)
                    await session.connect_client(reader, writer, config)
                    if reader.at_eof():
                        break
        finally:
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
        task = current_task()
        self.client_tasks.add(task)
        try:
            await self._handle_client(reader, writer)
        except CancelledError:
            writer.close()
            raise
        except:
            print_to_ctty(f'Madbg - error handling client:\n{format_exc()}')
            writer.close()
            raise
        finally:
            self.client_tasks.discard(task)

    async def _serve(self):
        # TODO: support all addr types
        assert isinstance(self.addr, tuple) and isinstance(self.addr[0], str) and isinstance(self.addr[1], int)
        ip, port = self.addr
        print_to_ctty(f'Listening for debugger clients on {ip}:{port}')
        server = await start_server(self._try_handle_client, ip, port)
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

    def _cancel(self):
        # Disconnect clients first, as since python 3.12 serve_forever waits for all connections to close.
        for task in self.client_tasks:
            task.cancel()
        if self.serve_task is not None:
            self.serve_task.cancel()

    def run(self):
        self.loop.run_until_complete(self._async_run())
        self.future.set_result(None)

    @classmethod
    def make_sure_listening_at(cls, addr: Addr) -> DebuggerServer:
        """
        This code might be called from injected code, so make it as simple and short as possible.
        """
        if cls.INSTANCE is None:
            self = cls(addr)
            self.start()
            # Stop before non-daemon threads are joined, as our apps keep some of them running
            getattr(threading, '_register_atexit', atexit.register)(DebuggerServer.stop)
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
        return cls.INSTANCE

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
                cls.INSTANCE.loop.call_soon_threadsafe(cls.INSTANCE._cancel)
                # Wait for server to finish
                cls.INSTANCE.future.result()


"""
Bugs:
    Less important:
        - c-c on original terminal when debugger is open cancels future commands
        - trying to attach to two threads in parallel (two threads asleep, c-c to both) - one gets stuck.
        - when writing ? in the terminal, "Object `` not found." is printed to stdout

Features:
    Important:
        - ui plans
        - support multiple clients - need to redraw app when new client connects
    Less important:
        - client cleanup doesn't completely reset terminal, when app exits not clean, client terminal is dead
        - client-level detach - support pause with c-z and quit with c-q or c-\
        - allow snooping stdios

Improvements:
    Important:
        - run in thread using ptrace - better than signal??
          signal: interfering with signal handlers
          ptrace: invoke subprocess, load dll
              which of them is more reentrant?
              can we at least verify the dest thread is blocked on a syscall? this is probable as we are holding
              the gil.
              do we have another approach?
        - signal.siginterrupt - use to attach to threads in syscalls?
        - use the new api for setting trace on other threads
        - pyinjector issues:
            - getting the python error back to us or at least know that it failed
            - deadlock
        - how does pydevd attach
    Less important:
        - once we set trace on a thread, maybe during continue we don't cancel the trace but just don't invoke the debugger,
          then we don't have to reattach the thread
        - get rid of piping

TODO:
    - move madbg.threads.run_in_thread into hypno
    - support mac n windows
    

UI
    There are three views:
        1. Main debugger
            - See all threads
            - Choose a thread
            - Quit
            - skip if there is only one thread?
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
"""
