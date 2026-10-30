"""Pacote principal inflatrack."""

import sys

# 1. Registrar common.bronze primeiro para evitar dependência circular
from inflatrack.common import bronze

sys.modules["inflatrack.bronze"] = bronze

# 2. Importar os clients
from inflatrack.clients import (  # noqa: E402
    alphavantage,
    dieese,
    dolar_olinda,
    inmet,
    pib,
    selic_sgs,
    sidra,
)

sys.modules["inflatrack.alphavantage"] = alphavantage
sys.modules["inflatrack.dieese"] = dieese
sys.modules["inflatrack.dolar_olinda"] = dolar_olinda
sys.modules["inflatrack.inmet"] = inmet
sys.modules["inflatrack.pib"] = pib
sys.modules["inflatrack.selic_sgs"] = selic_sgs
sys.modules["inflatrack.sidra"] = sidra

__all__ = [
    "alphavantage",
    "bronze",
    "dieese",
    "dolar_olinda",
    "inmet",
    "pib",
    "selic_sgs",
    "sidra",
]
