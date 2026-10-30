"""Pacote principal inflatrack."""

import sys

# 1. Registrar common.bronze primeiro para evitar dependência circular
from inflatrack.common import bronze

sys.modules["inflatrack.bronze"] = bronze

# 2. Importar os clients e registrar em sys.modules para retrocompatibilidade
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

# 3. Importar os loaders e registrar em sys.modules
from inflatrack.loaders import (  # noqa: E402
    load_clima,
    load_commodities,
    load_pib,
    load_pib_china,
    load_salario_minimo,
)

sys.modules["inflatrack.load_clima"] = load_clima
sys.modules["inflatrack.load_commodities"] = load_commodities
sys.modules["inflatrack.load_pib"] = load_pib
sys.modules["inflatrack.load_pib_china"] = load_pib_china
sys.modules["inflatrack.load_salario_minimo"] = load_salario_minimo

__all__ = [
    "alphavantage",
    "bronze",
    "dieese",
    "dolar_olinda",
    "inmet",
    "load_clima",
    "load_commodities",
    "load_pib",
    "load_pib_china",
    "load_salario_minimo",
    "pib",
    "selic_sgs",
    "sidra",
]
