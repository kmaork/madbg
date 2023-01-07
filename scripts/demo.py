from threading import Thread

import time
import madbg

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
a()
