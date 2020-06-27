from pytest import fixture
from IPython.terminal.interactiveshell import TerminalInteractiveShell


@fixture(scope='session', autouse=True)
def fix_ipython():
    TerminalInteractiveShell.simple_prompt = False
