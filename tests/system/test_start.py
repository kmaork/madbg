import time

from .utils import CTRL_C

MAIN_THREAD, WORKER_THREAD = 0, 1


def test_start_attach_to_main_thread(port, debuggee, client):
    script = debuggee('start.py', port)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('c')
    # Continuing gets us back to the running thread view
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    assert c.wait() == 0
    exit_code, output = script.wait()
    assert exit_code == 0
    assert 'RESULT done' in output


def test_start_attach_to_other_thread_and_connect_again(port, debuggee, client):
    script = debuggee('start.py', port)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(WORKER_THREAD)
    c.expect('Worker - running')
    c.process.send(CTRL_C)
    c.run('p worker_value > 0', thread='Worker')
    assert '\nTrue\r' in c.run('q', thread='Worker')
    c.exit_thread_menu()
    assert c.wait() == 0
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    assert script.wait()[0] == 0


def test_client_death_resumes_thread(port, debuggee, client):
    """ Issue #7 - a client that dies mid session should not leave the thread stopped """
    script = debuggee('start.py', port)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    # Die while a command runs, when there's no prompt to exit
    c.run('import time; time.sleep(1)')
    # The prompt disables bracketed paste once it accepts the command
    c.expect(r'\x1b\[\?2004l')
    c.kill()
    # Reconnect only after the command is done, so the thread resumes rather than waiting for us in the prompt
    time.sleep(2)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    assert script.wait()[0] == 0


def test_debuggee_exits_while_client_watches(port, debuggee, client):
    script = debuggee('start.py', port)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    # The debuggee exits even though the client is still connected and viewing the running thread
    exit_code, output = script.wait()
    assert exit_code == 0
    assert 'Task was destroyed' not in output
    assert c.wait() == 0


def test_second_client_joins_running_view_and_prompt(port, debuggee, client):
    script = debuggee('start.py', port)
    c1 = client('connect', '127.0.0.1', port)
    c1.choose_thread(MAIN_THREAD)
    c1.expect('MainThread - running')
    c2 = client('connect', '127.0.0.1', port)
    c2.choose_thread(MAIN_THREAD)
    c2.expect('MainThread - running')
    c1.process.send(CTRL_C)
    c1.expect(r'\x1b\[\?2004h[^\n]*MainThread>')
    c3 = client('connect', '127.0.0.1', port)
    c3.choose_thread(MAIN_THREAD)
    # A client joining a thread that is already stopped gets the prompt too
    c3.run('conti = False')
    c3.run('c')
    assert script.wait()[0] == 0


def test_leave_mid_prompt_and_reconnect_immediately(port, debuggee, client):
    script = debuggee('start.py', port)
    for _ in range(4):
        c = client('connect', '127.0.0.1', port)
        c.choose_thread(MAIN_THREAD)
        c.expect('MainThread - running')
        c.process.send(CTRL_C)
        c.expect(r'\x1b\[\?2004h[^\n]*MainThread>')
        c.kill()
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    assert script.wait()[0] == 0


def test_ctrl_d_quits_to_thread_menu(port, debuggee, client):
    script = debuggee('start.py', port)
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.expect(r'\x1b\[\?2004h[^\n]*MainThread>')
    c.process.send('\x04')
    c.exit_thread_menu()
    assert c.wait() == 0
    script.kill()


def test_client_dies_in_thread_menu(port, debuggee, client):
    script = debuggee('start.py', port)
    c = client('connect', '127.0.0.1', port)
    c.expect('Choose a thread')
    c.kill()
    c = client('connect', '127.0.0.1', port)
    c.choose_thread(MAIN_THREAD)
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    assert script.wait()[0] == 0
