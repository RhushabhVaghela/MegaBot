# Dependency Injection Container
"""
Centralized dependency injection system for MegaBot.
Provides service registration, resolution, and lifecycle management.

Note: Registration methods use a threading.Lock because they run at startup
*before* the async event loop serves requests.  resolve() is lock-free
because the dictionaries are only mutated during startup.  If you ever need
to register services while the event loop is running, switch to
asyncio.Lock (and make the registration methods ``async``).
"""

import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from core.config import Config

T = TypeVar("T")


class DependencyContainer:
    """Simple dependency injection container with singleton and factory support."""

    def __init__(self):
        self._services: dict[type, Any] = {}
        self._factories: dict[type, Callable[[], Any]] = {}
        self._singletons: dict[type, Any] = {}
        self._lock = threading.Lock()

    def register(self, service_type: type[T], implementation: T) -> None:
        """Register a service instance."""
        with self._lock:
            self._services[service_type] = implementation

    def register_factory(self, service_type: type[T], factory: Callable[[], T]) -> None:
        """Register a factory function for creating service instances."""
        with self._lock:
            self._factories[service_type] = factory

    def register_singleton(self, service_type: type[T], implementation: T) -> None:
        """Register a singleton service instance."""
        with self._lock:
            self._singletons[service_type] = implementation

    def resolve(self, service_type: type[T]) -> T:
        """Resolve a service instance.

        This method is intentionally lock-free for performance.
        It is safe as long as registrations only happen during startup
        (before the event loop serves concurrent requests).
        """
        # Check singletons first
        if service_type in self._singletons:
            return self._singletons[service_type]

        # Check registered services
        if service_type in self._services:
            return self._services[service_type]

        # Check factories
        if service_type in self._factories:
            instance = self._factories[service_type]()
            # Cache as singleton if it's meant to be one
            if hasattr(instance, "_singleton") and instance._singleton:
                self._singletons[service_type] = instance
            return instance

        # Try to create instance directly (for simple services)
        try:
            return service_type()
        except TypeError:
            raise ValueError(f"No registration found for service type: {service_type}") from None

    def has_service(self, service_type: type[T]) -> bool:
        """Check if a service is registered."""
        return service_type in self._services or service_type in self._factories or service_type in self._singletons

    def clear(self) -> None:
        """Clear all registered services (useful for testing)."""
        with self._lock:
            self._services.clear()
            self._factories.clear()
            self._singletons.clear()


# Global container instance
_container = DependencyContainer()


def get_container() -> DependencyContainer:
    """Get the global dependency container."""
    return _container


def inject(service_type: type[T]) -> Callable:
    """Decorator to inject dependencies into functions/classes."""

    def decorator(func_or_class):
        if isinstance(func_or_class, type):
            # It's a class, inject into __init__
            original_init = func_or_class.__init__

            def injected_init(self, *args, **kwargs):
                # Inject services before calling original __init__
                annotations = getattr(func_or_class, "__annotations__", {})
                for param_name, param_type in annotations.items():
                    if param_name != "return" and param_name not in kwargs and param_name not in ["self"]:
                        try:
                            kwargs[param_name] = _container.resolve(param_type)
                        except ValueError:
                            pass  # Optional dependency
                return original_init(self, *args, **kwargs)

            func_or_class.__init__ = injected_init
            return func_or_class
        else:
            # It's a function, inject into function call
            def injected_func(*args, **kwargs):
                # Inject services
                annotations = getattr(func_or_class, "__annotations__", {})
                for param_name, param_type in annotations.items():
                    if param_name != "return" and param_name not in kwargs:
                        try:
                            kwargs[param_name] = _container.resolve(param_type)
                        except ValueError:
                            pass  # Optional dependency
                return func_or_class(*args, **kwargs)

            return injected_func

    return decorator


@contextmanager
def dependency_scope():
    """Context manager for scoped dependencies (useful for testing)."""
    global _container
    old_container = _container
    _container = DependencyContainer()
    try:
        yield _container
    finally:
        _container = old_container


# Service registration helpers
def register_service(service_type: type[T], implementation: T) -> None:
    """Register a service instance."""
    _container.register(service_type, implementation)


def register_factory(service_type: type[T], factory: Callable[[], T]) -> None:
    """Register a service factory."""
    _container.register_factory(service_type, factory)


def register_singleton(service_type: type[T], implementation: T) -> None:
    """Register a singleton service."""
    _container.register_singleton(service_type, implementation)


def resolve_service(service_type: type[T]) -> T:
    """Resolve a service instance."""
    return _container.resolve(service_type)


# Common service types
class ServiceTypes:
    """Common service type constants."""

    CONFIG = Config
    # Add more as needed
