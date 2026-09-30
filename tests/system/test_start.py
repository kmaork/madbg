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
    c.run('p conti')
    c.kill()
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
