import sys
import madbg


def divide(a, b):
    return a / b


try:
    divide(1, 0)
except ZeroDivisionError:
    madbg.post_mortem(addr=('127.0.0.1', int(sys.argv[1])))
print('RESULT done')
