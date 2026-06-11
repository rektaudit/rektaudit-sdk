"""Backward-compatible import path for the main RektAudit monorepo."""

from pathlib import Path
import sys

_sdk_dir = Path(__file__).resolve().parent
if str(_sdk_dir) not in sys.path:
    sys.path.insert(0, str(_sdk_dir))

from rektaudit.client import RektauditClient, RektauditError, __version__

__all__ = ["RektauditClient", "RektauditError", "__version__"]