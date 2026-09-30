import ctypes
import time

# Allow madbg attach to ptrace us even when yama's ptrace_scope is 1
PR_SET_PTRACER, PR_SET_PTRACER_ANY = 0x59616d61, ctypes.c_ulong(-1)
ctypes.CDLL(None).prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0)
conti = True
print('READY', flush=True)
while conti:
    time.sleep(0.01)
print('RESULT done')
