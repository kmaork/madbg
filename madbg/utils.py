from functools import wraps, update_wrapper
from threading import Lock, get_ident


class thread_safe(object):
    def __init__(self, func):
        self.func = func
        self.lock = Lock()
        self.acquired_thread = None
        update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        current_thread = get_ident()
        if self.acquired_thread == current_thread:
            raise RuntimeError('Deadlock :(')
        with self.lock:
            try:
                self.acquired_thread = current_thread
                return self.func(*args, **kwargs)
            finally:
                self.acquired_thread = None


def wrap_callable(callable):
    """
    A callable doesn't necessarily behave like a function.
    For example, if it doesn't implement __get__ correctly, it cannot be bound to an instance if put on a class.
    Instead of implementing this function like logic, you can just wrap it with a normal function using wrap_callable().
    """

    @wraps(callable)
    def wrapper(*args, **kwargs):
        return callable(*args, **kwargs)

    return wrapper


class LazyInit(type):
    """
    Instances of classes with this metaclass are not initialized until their __getattr__ is called.
    """

    def __init__(cls, *args, **kwargs):
        super(LazyInit, cls).__init__(*args, **kwargs)
        cls.__has_getattr = hasattr(cls, '__getattr__')
        cls.__old_getattr = cls.__getattr__ if cls.__has_getattr else None
        # We are wrapping with a lambda because cls.__temp_getattr is a bound method and it won't rebind to self
        temp_getattr = wrap_callable(cls.__temp_getattr)
        if cls.__has_getattr:
            temp_getattr = update_wrapper(temp_getattr, cls.__old_getattr)
        cls.__getattr__ = temp_getattr

    def __call__(cls, *args, **kwargs):
        instance = cls.__new__(cls, *args, **kwargs)
        instance.__init_args = args
        instance.__init_kwargs = kwargs
        instance.__initialized = False
        return instance

    @staticmethod
    def initialize_lazy_object(self):
        self.__init__(*self.__init_args, **self.__init_kwargs)
        self.__initialized = True

    @wrap_callable
    @thread_safe
    def __temp_getattr(cls, self, attr):
        if not self.__initialized:
            cls.initialize_lazy_object(self)
            return getattr(self, attr)
        if cls.__has_getattr:
            return cls.__old_getattr(self, attr)
        raise AttributeError(attr)
