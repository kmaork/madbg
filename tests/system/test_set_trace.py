def test_set_trace(port, debuggee, client):
    script = debuggee('set_trace.py', port, 1, '')
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    c.run('value += 1')
    c.run('c')
    assert c.wait() == 0
    exit_code, output = script.wait()
    assert exit_code == 0
    assert 'RESULT 1' in output


def test_set_trace_twice_and_continue(port, debuggee, client):
    script = debuggee('set_trace.py', port, 2, '')
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    c.run('value += 1')
    c.run('c')
    # The second set_trace stops the thread again, and the connected client gets the prompt
    c.run('value += 1')
    c.run('c')
    assert c.wait() == 0
    assert 'RESULT 2' in script.wait()[1]


def test_set_trace_and_quit_then_connect_again(port, debuggee, client):
    script = debuggee('set_trace.py', port, 2, '')
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    c.run('q')
    # Quitting the debugger returns to the thread menu
    c.exit_thread_menu()
    assert c.wait() == 0
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    c.run('c')
    assert c.wait() == 0
    assert script.wait()[0] == 0


def test_set_trace_with_failing_debugger(port, debuggee):
    exit_code, output = debuggee('set_trace.py', port, 1, 'fail').wait()
    assert exit_code != 0
    assert ZeroDivisionError.__name__ in output
