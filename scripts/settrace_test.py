import sys

def x():
    4 + 4

def a():
    b()
    1 + 1
    x()
    sys.settrace(None)

def b():
    c()
    2 + 2

def c():
    def p(*a):
        print(*a)
        return p
    sys.settrace(p)
    3 + 3

a()