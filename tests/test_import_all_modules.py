"""Every module in every package must import cleanly."""
import importlib
import pkgutil

import pytest

import agip_shared
import calm_generation
import governance_execution
import rule_authoring

PACKAGES = [agip_shared, rule_authoring, calm_generation, governance_execution]


def _module_names():
    for pkg in PACKAGES:
        yield pkg.__name__
        for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            yield m.name


@pytest.mark.parametrize("name", sorted(set(_module_names())))
def test_module_imports(name):
    importlib.import_module(name)
