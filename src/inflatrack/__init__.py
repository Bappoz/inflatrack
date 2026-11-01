"""Pacote principal inflatrack."""

import importlib
import sys

# 1. Subpacotes principais
from inflatrack import clients, common, loaders  # noqa: F401

# 2. Clientes para compatibilidade
_CLIENT_NAMES = [
    "alphavantage",
    "dieese",
    "dolar_olinda",
    "inmet",
    "pib",
    "selic_sgs",
    "sidra",
]
for _name in _CLIENT_NAMES:
    _mod = importlib.import_module(f"inflatrack.clients.{_name}")
    sys.modules[f"inflatrack.{_name}"] = _mod
    setattr(sys.modules[__name__], _name, _mod)

# 3. Loaders para compatibilidade
_LOADER_NAMES = [
    "load_clima",
    "load_commodities",
    "load_dolar",
    "load_pib",
    "load_pib_china",
    "load_salario_minimo",
    "load_selic",
]
for _name in _LOADER_NAMES:
    _mod = importlib.import_module(f"inflatrack.loaders.{_name}")
    sys.modules[f"inflatrack.{_name}"] = _mod
    setattr(sys.modules[__name__], _name, _mod)

# 4. Módulos bronze_* primeiro (pois ingest_* dependem de bronze_*)
_BRONZE_NAMES = [
    "bronze_clima",
    "bronze_dolar",
    "bronze_ipca",
    "bronze_pib",
    "bronze_pib_china",
    "bronze_pib_russia",
    "bronze_pib_usa",
    "bronze_salario_minimo",
    "bronze_selic",
    "dolar",
    "selic",
]
for _name in _BRONZE_NAMES:
    _mod = importlib.import_module(f"inflatrack.bronze.{_name}")
    sys.modules[f"inflatrack.{_name}"] = _mod
    setattr(sys.modules[__name__], _name, _mod)

# 5. Módulos ingest_*
_INGEST_NAMES = [
    "ingest",
    "ingest_clima",
    "ingest_commodities",
    "ingest_dolar",
    "ingest_pib",
    "ingest_pib_china",
    "ingest_pib_russia",
    "ingest_pib_usa",
    "ingest_salario_minimo",
    "ingest_selic",
]
for _name in _INGEST_NAMES:
    _mod = importlib.import_module(f"inflatrack.bronze.{_name}")
    sys.modules[f"inflatrack.{_name}"] = _mod
    setattr(sys.modules[__name__], _name, _mod)

from inflatrack import bronze  # noqa: E402, F401

__all__ = [
    "bronze",
    "clients",
    "common",
    "loaders",
    *_CLIENT_NAMES,
    *_LOADER_NAMES,
    *_BRONZE_NAMES,
    *_INGEST_NAMES,
]
