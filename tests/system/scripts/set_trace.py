import sys
import madbg
from madbg.debugger import RemoteIPythonDebugger

port, times, fail = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == 'fail'
if fail:
    RemoteIPythonDebugger.__init__ = lambda *a, **k: 1 / 0
value = 0
for _ in range(times):
    madbg.set_trace(addr=('127.0.0.1', port))
print('RESULT', value)
