from multiprocessing import Process, Value
import pty
import os
from pytest import mark
import madbg
import madbg.client

STDIN_FILENO = 0
STDOUT_FILENO = 1
STDERR_FILENO = 2

JOIN_TIMEOUT = 3


def enter_pty(attach_as_ctty):
    os.setsid()
    master_fd, slave_fd = pty.openpty()
    if attach_as_ctty:
        os.close(os.open(os.ttyname(slave_fd), os.O_RDWR))  # Set the PTY to be our CTTY
    os.dup2(slave_fd, STDIN_FILENO)
    os.dup2(slave_fd, STDOUT_FILENO)
    os.dup2(slave_fd, STDERR_FILENO)
    return master_fd


def run_set_trace_process(value_to_change, start_with_ctty):
    enter_pty(start_with_ctty)
    # value_to_change is expected to be changed by the debugger
    madbg.set_trace()


def run_client_process(new_value):
    master_fd = enter_pty(True)
    os.write(master_fd, 'value_to_change.value = {}\nc\n'.format(new_value).encode())
    madbg.client.debug()


@mark.parametrize('start_debugger_with_ctty', (True, False))
def test_set_trace(start_debugger_with_ctty):
    # TODO: test more edge cases and ipdb commands
    value_to_change = Value('l', 0)
    new_value = 1
    debugger_process = Process(target=run_set_trace_process, args=(value_to_change, start_debugger_with_ctty))
    client_process = Process(target=run_client_process, args=(new_value,))
    debugger_process.start()
    client_process.start()
    client_process.join(JOIN_TIMEOUT)
    debugger_process.join(JOIN_TIMEOUT)
    print(value_to_change.value, new_value)  # TODO: make tests work with pytest
    assert value_to_change.value == new_value


if __name__ == '__main__':
    test_set_trace(True)
    test_set_trace(False)
