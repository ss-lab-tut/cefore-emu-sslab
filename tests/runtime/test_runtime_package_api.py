import importlib
from types import ModuleType

import pytest

import src.runtime as runtime


@pytest.mark.parametrize(
    ("export_name", "module_name"),
    sorted(runtime._EXPORT_MODULES.items()),
)
def test_runtime_lazy_export_points_to_declared_module_attribute(
    export_name: str, module_name: str
) -> None:
    module = importlib.import_module(module_name, runtime.__name__)
    exported = getattr(runtime, export_name)

    assert exported is getattr(module, export_name)
    if not isinstance(exported, ModuleType) and hasattr(exported, "__module__"):
        assert _absolute_module_name(module_name) == exported.__module__


def _absolute_module_name(module_name: str) -> str:
    if module_name.startswith("."):
        return f"{runtime.__name__}{module_name}"
    return module_name
