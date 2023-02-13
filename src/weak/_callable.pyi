"""pyi file required until mypyc supports ParamSpec."""

import weakref
from typing import Any, Callable, Generic, ParamSpec, TypeVar

T = TypeVar("T")
R = TypeVar("R")
P = ParamSpec("P")

class WeakCallable(Generic[P, R]):
    """Weak reference to a callable."""

    _obj_ref: weakref.ReferenceType[Any]
    _max_args: int | None = None

    def callback(self, args: tuple[Any, ...] = ()) -> bool:
        """Call the referenced function. Return True if weakref is dead.

        This implementation should be as fast as possible.
        """
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the referenced function.  Raise a RuntimeError if it is dead."""
    def __eq__(self, other: object) -> bool:
        """Return True if `other` is equal to this WeakCallback."""
    def slot(self) -> Callable[P, R]:
        """Reconstruct the original slot, or raise a RuntimeError."""
    def is_alive(self) -> bool:
        """Return True if the slot is still alive."""
    @classmethod
    def create(
        cls, func: Callable[P, R], max_args: int | None = None, key: str | None = None
    ) -> WeakCallable[P, R]: ...
    @classmethod
    def partial(
        cls, func: Callable[..., R], *args: Any, **kwargs: Any
    ) -> weak_partial: ...

class _SetitemCaller(WeakCallable):
    _key: str
    def __init__(
        self, obj: weakref.ReferenceType | Any, attr: str, max_args: int | None = None
    ) -> None: ...

class _SetattrCaller(WeakCallable):
    _key: Any
    def __init__(
        self, obj: weakref.ReferenceType | Any, key: Any, max_args: int | None = None
    ) -> None: ...

class weak_partial(WeakCallable[P, R]):
    def __init__(self, func: Callable[P, R], *args: Any, **kwargs: Any) -> None: ...
