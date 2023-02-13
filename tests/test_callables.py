import weakref
from functools import partial
from typing import Any
from unittest.mock import Mock

import pytest
from weak._callable import WeakCallable, weak_partial

VAL = 42


def _make_ref_and_caller(
    obj: Any, target: Any = None, key: Any = None, returns: Any = VAL
) -> tuple[weakref.ReferenceType, WeakCallable]:
    ref = weakref.ref(obj)
    caller: "WeakCallable[[int], Any]" = WeakCallable.create(target or obj, key=key)
    assert caller(VAL) == returns
    return ref, caller


def _assert_dead(ref: weakref.ref, caller: "WeakCallable[[int], Any]") -> None:
    assert not ref()
    assert not caller.is_alive()
    assert caller.callback((VAL,)) is True
    with pytest.raises(RuntimeError):
        caller(VAL)


def test_weak_mock_caller():
    # make sure mocks work when connected... for the sake of testing.
    mock = Mock()
    caller = WeakCallable.create(mock)
    caller(1)
    mock.assert_called_once_with(1)

    mock.reset_mock()
    caller.callback((2,))
    mock.assert_called_once_with(2)


def test_weak_function_caller() -> None:
    def func(x: int) -> int:
        return x

    ref, caller = _make_ref_and_caller(func)
    del func
    _assert_dead(ref, caller)


def test_weak_method_caller() -> None:
    class Foo:
        def func(self, x: int) -> int:
            return x

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, foo.func)
    del foo
    _assert_dead(ref, caller)


def test_weak_partial_method_caller() -> None:
    class Foo:
        def func(self, y: int, x: int) -> int:
            return x

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, partial(foo.func, 2345))
    del foo
    _assert_dead(ref, caller)


def test_weak_setattr_caller() -> None:
    class Foo:
        x: int = 0

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, foo.__setattr__, key="x", returns=None)
    del foo
    _assert_dead(ref, caller)


def test_weak_setitem_caller() -> None:
    class Foo:
        x: int = 0

        def __setitem__(self, key: str, value: int) -> None:
            assert key == "x"
            self.x = value

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, foo.__setitem__, key="x", returns=None)
    del foo
    _assert_dead(ref, caller)


def test_weak_partial() -> None:
    class T:
        ...

    class C:
        def func(self, obj: T, x: Any, *, y: Any) -> T:
            self.x = x
            self.y = y
            return obj

    t = T()
    c = C()

    ref_t = weakref.ref(t)

    # t is closed over by the partial, so it would otherwise not be collected
    caller = weak_partial(c.func, t, y="y")
    # also works with a regular functools.partial
    caller2 = weak_partial(partial(c.func, t, y="y"))
    assert caller("x") is t
    assert c.x == "x"
    assert c.y == "y"
    assert caller2("w") is t
    assert c.x == "w"

    del t
    assert not ref_t()

    assert not caller.is_alive()
    assert not caller2.is_alive()
    assert caller.callback(("z",)) is True
    assert caller2.callback(("z",)) is True
    with pytest.raises(RuntimeError):
        caller("x")
    with pytest.raises(RuntimeError):
        caller2("x")
