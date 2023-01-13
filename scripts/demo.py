import signal
from threading import Thread
import faulthandler
import time
import madbg


faulthandler.register(signum=signal.SIGQUIT)
madbg.start()


def a():
    while True:
        time.sleep(2)
        print('Hello main thread')


def b():
    while True:
        time.sleep(2)
        print('Hello second thread')


Thread(target=b, name='SecondThread', daemon=True).start()
try:
    a()
except KeyboardInterrupt:
    pass
