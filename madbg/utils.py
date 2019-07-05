from functools import wraps


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
        # TODO: use functools.update_wrapper when possible
        cls.__getattr__ = wrap_callable(cls.__temp_getattr)

    def __call__(cls, *args, **kwargs):
        instance = cls.__new__(cls, *args, **kwargs)
        instance.__init_args = args
        instance.__init_kwargs = kwargs
        instance.__initialized = False
        return instance

    @staticmethod
    def __initialize(self):
        self.__init__(*self.__init_args, **self.__init_kwargs)

    def __temp_getattr(cls, self, attr):
        if not self.__initialized:
            cls.__initialize(self)
            self.__initialized = True
            return getattr(self, attr)
        if cls.__has_getattr:
            return cls.__old_getattr(self, attr)
        raise AttributeError(attr)
