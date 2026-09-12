"""Load the pure calendar logic without requiring a Home Assistant runtime."""

import importlib.util
import sys
import types
from pathlib import Path

PACKAGE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ha_remote_calendar_retain"
)
PACKAGE = "retain_under_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE] = package


def load_module(name):
    """Load integration modules without executing the platform entry point."""
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", PACKAGE_PATH / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
