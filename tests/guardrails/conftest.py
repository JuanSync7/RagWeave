"""Conftest for guardrails tests.

Fixes a broken langchain_core pre-import caused by the langsmith pytest plugin.
The plugin loads langchain_core during initialization but leaves it in a broken
state (no __path__, no __spec__). We clean it from sys.modules so nemoguardrails
can import it properly.
"""
import sys

# Remove broken langchain_core ghost modules so they can be re-imported cleanly
_to_remove = [key for key in sys.modules if key == "langchain_core" or key.startswith("langchain_core.")]
for key in _to_remove:
    mod = sys.modules[key]
    if getattr(mod, "__spec__", None) is None and getattr(mod, "__path__", None) is None:
        del sys.modules[key]
