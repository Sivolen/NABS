"""
Lets the unit tests that only use mocks run on a machine where the heavy stack
(SQLAlchemy, Flask-SQLAlchemy, LDAP, Nornir, psycopg2 ...) is not installed.

    import nabs_test_stubs
    nabs_test_stubs.install_if_missing()   # first line of a test module

In the real environment (venv with requirements.txt, CI) this does NOTHING: the
tests then run against the real application and the real libraries.

When the stack is missing it
  * puts a lightweight `app` package in sys.modules (so app/__init__.py, which needs
    a database server, is not executed) - the real submodules (app.views.*,
    app.modules.*) are still imported from the source tree and really executed;
  * makes `app.models` a module whose classes are MagicMocks;
  * provides a `config` module built from config_example.py when there is no config.py;
  * replaces the missing third-party packages with mock modules.
This is NOT a replacement for running the tests in the real venv.
"""

import importlib.abc
import importlib.machinery
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent

# top-level packages replaced by mocks when the real stack is missing
STUBBED_PACKAGES = (
    "sqlalchemy",
    "flask_sqlalchemy",
    "flask_migrate",
    "flask_compress",
    "flask_wtf",
    "ldap3",
    "psycopg2",
    "apscheduler",
    "nornir",
    "nornir_napalm",
    "nornir_netmiko",
    "nornir_utils",
    "nornir_netbox",
    "napalm",
    "netmiko",
    "ruamel",
    "cryptocode",
    "bcrypt",
    "yaml",
    "differently",
    "paramiko",
)


class _MockModule(types.ModuleType):
    """A module whose every attribute is a MagicMock; submodules import fine."""

    def __init__(self, name):
        super().__init__(name)
        self.__path__ = []  # makes it a package: "import x.y.z" works

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        value = MagicMock(name=f"{self.__name__}.{item}")
        setattr(self, item, value)
        return value


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in STUBBED_PACKAGES:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        return _MockModule(spec.name)

    def exec_module(self, module):
        pass


def _real_stack_available() -> bool:
    try:
        import flask_sqlalchemy  # noqa: F401
        import sqlalchemy  # noqa: F401

        return True
    except ImportError:
        return False


def _install_config():
    try:
        import config  # noqa: F401  (a real config.py exists)

        return
    except ImportError:
        pass
    module = types.ModuleType("config")
    source = (ROOT / "config_example.py").read_text()
    exec(compile(source, "config_example.py", "exec"), module.__dict__)
    module.TOKEN = "t" * 32
    module.CREDENTIALS_ENCRYPTION_KEY = "k" * 32
    module.release_options = "TestingConfig"
    sys.modules["config"] = module


def _install_app_package():
    import flask

    package = types.ModuleType("app")
    package.__path__ = [str(ROOT / "app")]
    package.logger = logging.getLogger("nabs-test")
    package.db = MagicMock(name="db")
    package.app = flask.Flask("nabs-test-stub")
    package.__version__ = package.__ui__ = "test"
    sys.modules["app"] = package

    models = _MockModule("app.models")
    models.__path__ = []
    sys.modules["app.models"] = models
    package.models = models


def install_if_missing() -> bool:
    """Returns True when stubs were installed, False when the real stack is used."""
    if _real_stack_available():
        return False
    if "app" in sys.modules and getattr(sys.modules["app"], "_nabs_stub", False):
        return True
    if not any(isinstance(f, _StubFinder) for f in sys.meta_path):
        sys.meta_path.append(_StubFinder())
    sys.path.insert(0, str(ROOT))
    _install_config()
    _install_app_package()
    sys.modules["app"]._nabs_stub = True
    return True
