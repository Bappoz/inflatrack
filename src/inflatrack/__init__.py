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
    "worldbank",
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
    "load_pib_internacional",
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
    "bronze_pib",
    "bronze_salario_minimo",
    "dolar",
    "pib_internacional",
    "selic",
]
for _name in _BRONZE_NAMES:
    _mod = importlib.import_module(f"inflatrack.bronze.{_name}")
    sys.modules[f"inflatrack.{_name}"] = _mod
    setattr(sys.modules[__name__], _name, _mod)

# 5. Módulos ingest_*
_INGEST_NAMES = [
    "ingest_clima",
    "ingest_commodities",
    "ingest_pib",
    "ingest_salario_minimo",
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
