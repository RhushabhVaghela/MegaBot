import runpy
import sys
from unittest.mock import patch


def test_orchestrator_main_block():
    # Save ALL core.* modules so we can restore them after runpy re-executes
    # core.orchestrator.  runpy creates a fresh module namespace and
    # re-executing the orchestrator can cause transitive imports (e.g.
    # core.orchestrator_components, core.config, core.task_utils) to see
    # different module objects, polluting later tests that hold references
    # to the original module globals.
    saved_modules = {
        k: sys.modules[k] for k in list(sys.modules) if k.startswith("core.")
    }

    try:
        # Only clear the orchestrator module itself so runpy can re-execute it
        for k in list(sys.modules):
            if k == "core.orchestrator" or k.startswith("core.orchestrator."):
                del sys.modules[k]

        with patch("uvicorn.run") as mock_run:
            runpy.run_module("core.orchestrator", run_name="__main__")
            assert mock_run.called
    finally:
        # Restore ALL core.* modules so every other test sees the same
        # module objects (and the same globals dicts) that were imported at
        # collection time.  Also remove any NEW core.* entries that runpy
        # may have added.
        for k in list(sys.modules):
            if k.startswith("core."):
                if k in saved_modules:
                    sys.modules[k] = saved_modules[k]
                else:
                    del sys.modules[k]
        # Ensure nothing was missed
        for k, v in saved_modules.items():
            sys.modules[k] = v
