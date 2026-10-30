"""Pacote principal inflatrack."""

import sys

from inflatrack.common import bronze

sys.modules["inflatrack.bronze"] = bronze

__all__ = ["bronze"]
