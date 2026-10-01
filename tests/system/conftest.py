from pytest import fixture
from .utils import find_free_port, Debuggee, Client


@fixture
def port():
    return find_free_port()


@fixture(params=(True, False), ids=('ctty', 'no_ctty'))
def with_ctty(request):
    return request.param


@fixture
def processes():
    started = []
    yield started
    for process in started:
        process.kill()


@fixture
def debuggee(processes, with_ctty):
    def start(script, *args):
        process = Debuggee(script, *args, with_ctty=with_ctty)
        processes.append(process)
        return process

    return start


@fixture
def client(processes):
    def start(*madbg_args):
        process = Client(*madbg_args)
        processes.append(process)
        return process

    return start
