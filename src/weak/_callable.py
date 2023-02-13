from __future__ import annotations

import weakref
from functools import partial
from types import BuiltinMethodType, MethodType
from typing import TYPE_CHECKING, Any, Callable, Generic, Protocol, TypeVar, cast

if TYPE_CHECKING:
    from typing_extensions import TypeGuard

T = TypeVar("T")
R = TypeVar("R")
_LAMBDA_NAME = "<lambda>"  # (lambda: None).__name__ won't compile with mypyc


class BoundMethodType(Protocol[R]):
    __self__: Any
    __func__: Callable[..., R]
    __name__: str

    def __call__(self, *args: Any, **kwds: Any) -> R:
        ...


class PartialMethod(Protocol[R]):
    """Protocol for a bound method wrapped in partial.

    like: `partial(MyClass().some_method, y=1)`.

    We use this instead of partial[] so that we can specify what `func` is.
    """

    func: BoundMethodType[R]
    args: tuple[Any, ...]
    keywords: dict[str, Any]

    def __call__(self, *args: Any, **kwds: Any) -> R:
        ...


def _is_partial_method(obj: object) -> TypeGuard[PartialMethod]:
    """Return `True` of `obj` is a `functools.partial` wrapping a bound method."""
    return isinstance(obj, partial) and isinstance(obj.func, MethodType)


class WeakCallable(Generic[R]):
    """ABC for a "stored" slot.

    !!! note

        We're not using a real ABC here because PySide is doing some weird stuff
        that causes mypyc to complain with:

            src/psygnal/_signal.py:1108: in <module>
                class WeakCaller(ABC):
            E   TypeError: mypyc classes can't have a metaclass

        ...but *only* when PySide2 is imported (not with PyQt5).

    A WeakCaller is responsible for actually calling a stored slot during the
    `run_emit_loop`.  It is used to allow for different types of slots to be stored
    in a `SignalInstance` (such as a function, a bound method, a partial to a bound
    method), while still allowing them to be called in the same way.

    The main reason is that some slot types need to derefence a weakref during
    call time, while others don't.
    """

    _obj_ref: weakref.ReferenceType[Any]
    _max_args: int | None = None

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        """Call the referenced function. Return True if weakref is dead.

        This implementation should be as fast as possible.
        """
        raise NotImplementedError()

    def _prune_args(self, args: tuple) -> tuple[Any, ...]:
        return args[: self._max_args] if self._max_args is not None else args

    def __call__(self, *args: Any, **kwargs: Any) -> R:
        """Call the referenced function.  Raise a RuntimeError if it is dead."""
        return self.slot()(*self._prune_args(args))

    def __eq__(self, other: object) -> bool:
        """Return True if `other` is equal to this WeakCaller."""
        raise NotImplementedError()

    def slot(self) -> Callable[..., R]:
        """Reconstruct the original slot, or raise a RuntimeError."""
        raise NotImplementedError()

    def is_alive(self) -> bool:
        """Return True if the slot is still alive."""
        return self._obj_ref() is not None

    @classmethod
    def create(
        cls, func: Callable[..., R], max_args: int | None = None, key: str | None = None
    ) -> WeakCallable[R]:
        """Return a `WeakCaller` appropriate for `func`."""
        if isinstance(func, WeakCallable):
            return func
        if _is_partial_method(func):
            return _PartialMethodCaller(func, max_args)

        slot_name = getattr(func, "__name__", None)
        if key is not None and slot_name is not None:
            for method, caller_cls in (
                ("__setattr__", _SetattrCaller),
                ("__setitem__", _SetitemCaller),
            ):
                if method == slot_name:
                    if not hasattr(func, "__self__"):  # pragma: no cover
                        raise TypeError(
                            f"Cannot use {method} as a weak callback unless it is a "
                            "bound method."
                        )
                    return caller_cls(func.__self__, key, max_args)

        if isinstance(func, MethodType):
            return _BoundMethodCaller(func, max_args)
        elif isinstance(func, BuiltinMethodType):
            return _BuiltinMethodCaller(func, max_args)

        return _FunctionCaller(func, max_args)

    @classmethod
    def partial(cls, func: Callable[..., R], *args: Any, **kwargs: Any) -> weak_partial:
        return weak_partial(func, *args, **kwargs)


class _FunctionCaller(WeakCallable):
    """Simple caller of a plain function.

    Currently, this does not reference the function at all, so it will not prevent
    it from being garbage collected.
    """

    def __init__(self, func: Callable[..., R], max_args: int | None = None) -> None:
        try:
            self._obj_ref: weakref.ReferenceType[Callable[..., R]] = weakref.ref(func)
        except TypeError:
            # func is not weakrefable, so we just store it
            # TODO: warn?
            self._obj_ref = lambda: func  # type: ignore[assignment]
        qname = getattr(func, "__qualname__", "")
        if (
            getattr(func, "__name__", None) == _LAMBDA_NAME
            or "pyqtBoundSignal.emit" in qname
            or "SignalInstance.emit" in qname
        ):
            # special cases:
            # store a reference to the function for lambda functions, and for
            # pyqtBoundSignal.emit
            self._func = func
        self._max_args = max_args

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        func = self._obj_ref()
        if func is None:
            return True
        func(*self._prune_args(args))
        return False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FunctionCaller) and self._obj_ref == other._obj_ref

    def slot(self) -> Callable[..., R]:
        func = self._obj_ref()
        if func is None:
            raise RuntimeError("function has been deleted")
        return func


class _BoundMethodCaller(WeakCallable):
    """Caller of a (dereferenced) bound method."""

    def __init__(self, method: BoundMethodType[R], max_args: int | None = None) -> None:
        try:
            obj = method.__self__
            func = method.__func__
        except AttributeError:  # pragma: no cover
            raise TypeError(
                f"argument should be a bound method, not {type(method)}"
            ) from None

        self._obj_ref = weakref.ref(obj)
        self._func_ref: weakref.ReferenceType[Callable[..., R]] = weakref.ref(func)
        self._method_type = cast(
            Callable[[Callable[..., R], Any], BoundMethodType[R]], type(method)
        )
        self._max_args = max_args

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        obj = self._obj_ref()
        func = self._func_ref()
        if obj is None or func is None:
            return True
        func(obj, *self._prune_args(args))  # faster than self._method()(*args)
        return False

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _BoundMethodCaller)
            and self._obj_ref == other._obj_ref
            and self._func_ref == other._func_ref
        )

    def _method(self) -> BoundMethodType[R] | None:
        """Reconstruct the original method.

        Note: this isn't used above in __call__ because it's a bit slower
        """
        # sourcery skip: assign-if-exp, reintroduce-else
        obj = self._obj_ref()
        func = self._func_ref()
        if obj is None or func is None:
            return None
        return self._method_type(func, obj)

    def slot(self) -> BoundMethodType[R]:
        """Return original method or raise RuntimeError if it has been deleted."""
        method: BoundMethodType[R] | None = self._method()
        if method is None:
            raise RuntimeError("object has been deleted")  # pragma: no cover
        return method


class _BuiltinMethodCaller(WeakCallable[R]):
    """Caller of a (dereferenced) builtin bound method.

    builtin methods don't have a __func__ attribute, so we need to handle them
    separately.
    """

    def __init__(self, method: BuiltinMethodType, max_args: int | None = None) -> None:
        try:
            obj = method.__self__
            func_name = method.__name__
        except AttributeError:  # pragma: no cover
            raise TypeError(
                f"argument should be a builtin method, not {type(method)}"
            ) from None

        try:
            self._obj_ref = weakref.ref(obj)
        except TypeError:
            # obj is not weakrefable, so we just store it
            # TODO: warn?
            self._obj_ref = lambda: obj  # type: ignore[assignment]
        self._func_name = func_name
        self._max_args = max_args

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        obj = self._obj_ref()
        if obj is None:
            return True
        func = getattr(obj, self._func_name)
        func(*self._prune_args(args))  # faster than self._method()(*args)
        return False

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _BuiltinMethodCaller)
            and self._obj_ref == other._obj_ref
            and self._func_name == other._func_name
        )

    def _method(self) -> Callable[..., R] | None:
        """Reconstruct the original method.

        Note: this isn't used above in __call__ because it's a bit slower
        """
        # sourcery skip: assign-if-exp, reintroduce-else
        obj = self._obj_ref()
        if obj is None:
            return None
        return cast("Callable[..., R]", getattr(obj, self._func_name))

    def slot(self) -> Callable[..., R]:
        """Return original method or raise RuntimeError if it has been deleted."""
        method = self._method()
        if method is None:
            raise RuntimeError("object has been deleted")  # pragma: no cover
        return method


class _PartialMethodCaller(WeakCallable):
    """Caller of a partial to a (dereferenced) bound method."""

    def __init__(self, part: PartialMethod[R], max_args: int | None = None) -> None:
        method = part.func
        try:
            obj = method.__self__
            func = method.__func__
        except AttributeError:  # pragma: no cover
            raise TypeError(
                f"argument should be a bound method, not {type(method)}"
            ) from None

        self._obj_ref = weakref.ref(obj)
        self._func_ref: weakref.ReferenceType[Callable[..., R]] = weakref.ref(func)
        self._method_type = cast(
            Callable[[Callable[..., R], Any], BoundMethodType[R]], type(method)
        )
        self._max_args = max_args
        self._partial_args = part.args
        self._partial_kwargs = part.keywords

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        obj = self._obj_ref()
        func = self._func_ref()
        if obj is None or func is None:
            return True
        func(obj, *self._partial_args, *self._prune_args(args), **self._partial_kwargs)
        return False

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _PartialMethodCaller)
            and self._obj_ref == other._obj_ref
            and self._func_ref == other._func_ref
        )

    def _method(self) -> BoundMethodType[R] | None:
        """Reconstruct the original method.

        Note: this isn't used above in __call__ because it's a bit slower
        """
        # sourcery skip: assign-if-exp, reintroduce-else
        obj = self._obj_ref()
        func = self._func_ref()
        if obj is None or func is None:
            return None
        return self._method_type(func, obj)

    def slot(self) -> PartialMethod[R]:
        method: BoundMethodType[R] | None = self._method()
        if method is None:
            raise RuntimeError("object has been deleted")  # pragma: no cover
        _partial = partial(method, *self._partial_args, **self._partial_kwargs)
        return cast("PartialMethod[R]", _partial)


class _SetattrCaller(WeakCallable):
    """Caller to set an attribute on an object."""

    def __init__(
        self, obj: weakref.ReferenceType | Any, attr: str, max_args: int | None = None
    ) -> None:
        self._obj_ref = (
            obj if isinstance(obj, weakref.ReferenceType) else weakref.ref(obj)
        )
        self._key = attr
        self._max_args = max_args

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        obj = self._obj_ref()
        if obj is None:
            return True
        args = self._prune_args(args)
        setattr(obj, self._key, args[0] if len(args) == 1 else args)
        return False

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _SetattrCaller)
            and self._obj_ref == other._obj_ref
            and self._key == other._key
        )

    def slot(self) -> Callable:
        obj = self._obj_ref()
        if obj is None:
            raise RuntimeError("object has been deleted")
        return partial(setattr, obj, self._key)


class _SetitemCaller(WeakCallable):
    """Caller to call __setitem__ on an object."""

    def __init__(
        self, obj: weakref.ReferenceType | Any, key: Any, max_args: int | None = None
    ) -> None:
        self._obj_ref = (
            obj if isinstance(obj, weakref.ReferenceType) else weakref.ref(obj)
        )
        self._max_args = max_args
        self._key = key

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        obj = self._obj_ref()
        if obj is None:
            return True
        args = self._prune_args(args)
        obj[self._key] = args[0] if len(args) == 1 else args
        return False

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _SetitemCaller)
            and self._obj_ref == other._obj_ref
            and self._key == other._key
        )

    def slot(self) -> Callable:
        obj = self._obj_ref()
        if obj is None:
            raise RuntimeError("object has been deleted")
        return partial(obj.__setitem__, self._key)


def _try_ref(obj: T) -> Callable[[], T | None] | None:
    if obj is None:
        return None
    try:
        return weakref.ref(obj)
    except TypeError:
        return lambda: obj


class weak_partial(WeakCallable[R]):
    def __init__(self, func: Callable[..., R], *args: Any, **kwargs: Any) -> None:
        if not callable(func):
            raise TypeError("the first argument must be callable")

        if isinstance(func, partial):
            args = func.args + args
            kwargs = {**func.keywords, **kwargs}
            func = func.func

        self._self_ref: weakref.ReferenceType[Any] | None = None
        self._method_type: Callable[..., Callable[..., R]] | None = None
        if isinstance(func, MethodType):
            self._method_type = type(func)
            self._self_ref = weakref.ref(func.__self__)
            self._obj_ref = weakref.ref(func.__func__)
        else:
            self._obj_ref = weakref.ref(func)
        self._args = tuple(_try_ref(arg) for arg in args)
        self._kwargs = {k: _try_ref(v) for k, v in kwargs.items()}

    @property
    def func(self) -> Callable[..., R] | None:
        func = self._obj_ref()
        if func is None:
            return None
        if self._method_type is not None:
            obj = cast("weakref.ReferenceType[Any]", self._self_ref)()
            return None if obj is None else self._method_type(func, obj)
        return self._obj_ref()

    @property
    def args(self) -> tuple[Any, ...]:
        args = []
        for arg in self._args:
            if arg is not None:
                _arg = arg()
                if _arg is None:
                    raise RuntimeError("object in args has been deleted")
            else:
                _arg = None
            args.append(_arg)
        return tuple(args)

    @property
    def keywords(self) -> dict[str, Any]:
        kwargs = {}
        for k, v in self._kwargs.items():
            if v is not None:
                _v = v()
                if _v is None:
                    raise RuntimeError("object in kwargs has been deleted")
            else:
                _v = None
            kwargs[k] = _v
        return kwargs

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        func = self._obj_ref()
        if func is None:
            return True
        try:
            args = self.args + args
            kwargs = self.keywords
        except RuntimeError:
            return True

        if self._method_type is not None:
            # bound method
            obj = cast("weakref.ReferenceType[Any]", self._self_ref)()
            if obj is None:
                return True
            args = (obj, *args)

        func(*args, **kwargs)
        return False

    def __call__(self, *args: Any, **kwargs: Any) -> R:
        func = self.func
        if func is None:
            raise RuntimeError("object has been deleted")
        return func(*self.args, *args, **{**self.keywords, **kwargs})

    def is_alive(self) -> bool:
        try:
            self.args
        except RuntimeError:
            return False
        return super().is_alive() and self.func is not None
