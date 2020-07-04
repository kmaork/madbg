from pytest import fixture
from IPython.terminal.interactiveshell import TerminalInteractiveShell
from .utils import find_free_port


@fixture(scope='session', autouse=True)
def fix_ipython():
    TerminalInteractiveShell.simple_prompt = False


@fixture
def port():
    return find_free_port()


@fixture(params=(True, False))
def start_debugger_with_ctty(request):
    return request.param
