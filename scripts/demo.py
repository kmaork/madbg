#!/usr/bin/env python3.11
import signal
from threading import Thread
import faulthandler
import time

faulthandler.register(signum=signal.SIGQUIT)


def main():
    while True:
        'a'
        time.sleep(0.5)
        'b'
        time.sleep(0.5)
        'c'
        time.sleep(0.5)


def second():
    while True:
        '1'
        time.sleep(0.5)
        '2'
        time.sleep(0.5)
        '3'
        time.sleep(0.5)


Thread(target=second, name='SecondThread', daemon=True).start()
try:
    main()
except KeyboardInterrupt:
    pass
