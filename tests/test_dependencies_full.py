"""Tests for dependency injection system"""

import pytest

from core.dependencies import (
    DependencyContainer,
    dependency_scope,
    inject,
    register_service,
    resolve_service,
)


class MockService:
    def __init__(self, value="default"):
        self.value = value


class TestDependencyInjection:
    def test_container_register_resolve(self):
        container = DependencyContainer()
        service = MockService("test")
        container.register(MockService, service)

        resolved = container.resolve(MockService)
        assert resolved is service
        assert resolved.value == "test"

    def test_container_factory(self):
        container = DependencyContainer()
        container.register_factory(MockService, lambda: MockService("factory"))

        resolved = container.resolve(MockService)
        assert resolved.value == "factory"

    def test_container_singleton(self):
        container = DependencyContainer()
        service = MockService("singleton")
        container.register_singleton(MockService, service)

        resolved1 = container.resolve(MockService)
        resolved2 = container.resolve(MockService)
        assert resolved1 is resolved2 is service

    def test_dependency_scope(self):
        register_service(MockService, MockService("global"))
        assert resolve_service(MockService).value == "global"

        with dependency_scope() as scoped_container:
            scoped_container.register(MockService, MockService("scoped"))
            assert resolve_service(MockService).value == "scoped"

        assert resolve_service(MockService).value == "global"

    def test_inject_decorator_class(self):
        with dependency_scope() as container:
            service = MockService("injected")
            container.register(MockService, service)

            @inject(MockService)
            class Client:
                # Type annotation is used for injection
                service: MockService

                def __init__(self, service: MockService = None):
                    self.service = service

            client = Client()
            assert client.service is service
            assert client.service.value == "injected"

    def test_inject_decorator_function(self):
        with dependency_scope() as container:
            service = MockService("func_injected")
            container.register(MockService, service)

            # Annotation must be present before decorator is applied
            def base_function(service: MockService = None):
                return service

            # Verify annotation exists
            assert "service" in base_function.__annotations__

            injected_func = inject(MockService)(base_function)

            result = injected_func()
            assert result is service
            assert result.value == "func_injected"

    def test_container_has_service(self):
        container = DependencyContainer()
        container.register(MockService, MockService())
        assert container.has_service(MockService) is True
        assert container.has_service(str) is False

    def test_container_clear(self):
        container = DependencyContainer()
        container.register(MockService, MockService())
        container.clear()
        assert container.has_service(MockService) is False

    def test_direct_instantiation_fallback(self):
        container = DependencyContainer()
        # No registration for MockService
        resolved = container.resolve(MockService)
        assert isinstance(resolved, MockService)
        assert resolved.value == "default"

    def test_resolve_error(self):
        container = DependencyContainer()

        class Uninstantiable:
            def __init__(self, arg):  # Requires arg, can't be created directly
                pass

        with pytest.raises(ValueError, match="No registration found"):
            container.resolve(Uninstantiable)


def test_factory_with_singleton_property():
    """Test factory that returns an object with _singleton=True (line 54)"""
    from core.dependencies import DependencyContainer

    container = DependencyContainer()

    class SingletonService:
        def __init__(self):
            self._singleton = True

    container.register_factory(SingletonService, lambda: SingletonService())

    resolved1 = container.resolve(SingletonService)
    resolved2 = container.resolve(SingletonService)

    assert resolved1 is resolved2


def test_get_container():
    """Test get_container function (line 85)"""
    from core.dependencies import DependencyContainer, get_container

    container = get_container()
    assert isinstance(container, DependencyContainer)


def test_inject_optional_dependencies():
    """Test inject decorator with optional (unresolvable) dependencies (lines 107-108, 122-123)"""
    from core.dependencies import dependency_scope, inject

    class Unresolvable:
        def __init__(self, arg):
            pass  # Cannot be auto-instantiated

    with dependency_scope():
        # Class injection
        @inject(Unresolvable)
        class Client:
            dep: Unresolvable

            def __init__(self, dep=None):
                self.dep = dep

        client = Client()
        assert client.dep is None  # Should have passed on ValueError

        # Function injection
        @inject(Unresolvable)
        def func(dep: Unresolvable = None):
            return dep

        assert func() is None  # Should have passed on ValueError


def test_registration_helpers():
    """Test register_factory and register_singleton helper functions (lines 151, 156)"""
    from core.dependencies import (
        dependency_scope,
        register_factory,
        register_singleton,
        resolve_service,
    )

    class FactoryService:
        pass

    class SingletonService:
        pass

    with dependency_scope():
        register_factory(FactoryService, lambda: FactoryService())
        assert isinstance(resolve_service(FactoryService), FactoryService)

        s = SingletonService()
        register_singleton(SingletonService, s)
        assert resolve_service(SingletonService) is s
