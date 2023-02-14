import gc
import types
import weakref
from functools import partial
from typing import Any, Callable, Sized

import pytest


class weak_callable:
    def __init__(self, obj: Callable) -> None:
        if isinstance(obj, types.MethodType):
            _obj_proxy = weakref.ref(obj.__self__)
            _func_proxy = weakref.ref(obj.__func__)

            def _call(*args: Any, **kwds: Any) -> Any:
                obj = _obj_proxy()
                func = _func_proxy()
                if obj is None or func is None:
                    raise ReferenceError("weakly-referenced object no longer exists")
                return func(obj, *args, **kwds)

            self._callable = _call
        else:
            self._callable = weakref.proxy(obj)

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        return self._callable(*args, **kwds)


class Class(list):
    def method(self, x: Sized, y: str = "y") -> int:
        assert self is not None
        return x[0]  # type: ignore


@pytest.mark.parametrize(
    "callable_type",
    [
        "function",
        "lambda",
        "method",
        "partial",
        "builtin_function_type",
        "builtin_method_type",
    ],
)
def test_function(callable_type: str) -> None:
    obj = Class()
    func: Callable
    args = (1,)
    expect: Any = 1
    if callable_type == "function":

        def func(x: Sized) -> int:
            return x[0]  # type: ignore

        assert isinstance(func, types.FunctionType)
    elif callable_type == "lambda":
        func = lambda x: x[0]  # noqa
        assert isinstance(func, types.FunctionType)
        assert isinstance(func, types.LambdaType)
    elif callable_type == "method":
        func = obj.method
        assert isinstance(func, types.MethodType)
    elif callable_type == "partial":
        func = partial(obj.method, y="z")
    elif callable_type == "builtin_function_type":
        func = obj.count
        expect = 0
        assert isinstance(func, types.BuiltinFunctionType)
        assert isinstance(func, types.BuiltinMethodType)
    elif callable_type == "builtin_method_type":
        func = obj.append
        expect = None
        assert isinstance(func, types.BuiltinFunctionType)
        assert isinstance(func, types.BuiltinMethodType)
    else:
        raise NotImplementedError(callable_type)

    obj_ref = weakref.ref(obj)
    func_ref = weakref.ref(func)
    assert obj_ref() is obj
    assert func_ref() is func

    proxy = weak_callable(func)
    assert proxy(args) == expect

    del obj
    del func
    assert obj_ref() is None
    assert func_ref() is None
    with pytest.raises(ReferenceError):
        proxy(args)


# def test_builtin_function_type():
#     assert isinstance(len, types.BuiltinFunctionType)
#     proxy = weakref.proxy(len)
#     assert proxy([1, 2, 3]) == 3
