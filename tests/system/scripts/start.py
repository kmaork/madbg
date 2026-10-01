import sys
import time
import threading
import madbg

conti = worker_conti = True


def work():
    worker_value = 0
    while worker_conti:
        worker_value += 1
        time.sleep(0.01)


worker = threading.Thread(target=work, name='Worker')
worker.start()
madbg.start(('127.0.0.1', int(sys.argv[1])))
while conti:
    time.sleep(0.01)
worker_conti = False
worker.join()
print('RESULT done')
