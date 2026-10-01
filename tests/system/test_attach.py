from .utils import CTRL_C


def test_attach_to_process(port, debuggee, client):
    """ Issue #27 """
    script = debuggee('loop.py')
    # Wait for the script to allow being ptraced
    if script.with_ctty:
        script.process.expect('READY')
    else:
        assert script.process.stdout.readline().strip() == 'READY'
    c = client('attach', script.pid, port)
    c.choose_thread()
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('q')
    c.exit_thread_menu()
    assert c.wait() == 0
    # Attaching to a thread from inside the process overrides its PR_SET_PTRACER, so under yama's ptrace_scope=1 the
    # process can't be attached to again - but its debugger server is still up
    c = client('connect', '127.0.0.1', port)
    c.choose_thread()
    c.expect('MainThread - running')
    c.process.send(CTRL_C)
    c.run('conti = False')
    c.run('c')
    exit_code, output = script.wait()
    assert exit_code == 0
    assert 'RESULT done' in output
