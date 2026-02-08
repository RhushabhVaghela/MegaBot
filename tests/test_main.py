import runpy
import sys
from unittest.mock import patch


def test_orchestrator_main_block():
    # Save ALL megabot.core.* modules so we can restore them after runpy re-executes
    # megabot.core.orchestrator.  runpy creates a fresh module namespace and
    # re-executing the orchestrator can cause transitive imports (e.g.
    # megabot.core.orchestrator_components, megabot.core.config, megabot.core.task_utils)
    # to see different module objects, polluting later tests that hold references
    # to the original module globals.
    saved_modules = {k: sys.modules[k] for k in list(sys.modules) if k.startswith("megabot.core.")}

    try:
        # Only clear the orchestrator module itself so runpy can re-execute it
        for k in list(sys.modules):
            if k == "megabot.core.orchestrator" or k.startswith("megabot.core.orchestrator."):
                del sys.modules[k]

        with patch("uvicorn.run") as mock_run:
            runpy.run_module("megabot.core.orchestrator", run_name="__main__")
            assert mock_run.called
    finally:
        # Restore ALL megabot.core.* modules so every other test sees the same
        # module objects (and the same globals dicts) that were imported at
        # collection time.  Also remove any NEW megabot.core.* entries that runpy
        # may have added.
        for k in list(sys.modules):
            if k.startswith("megabot.core."):
                if k in saved_modules:
                    sys.modules[k] = saved_modules[k]
                else:
                    del sys.modules[k]
        # Ensure nothing was missed
        for k, v in saved_modules.items():
            sys.modules[k] = v
