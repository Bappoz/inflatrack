"""Ponto de entrada do Dagster: `uv run dagster dev` (ou `just orquestrador`)."""

import importlib
import pkgutil

from dagster import Definitions, load_asset_checks_from_modules, load_assets_from_modules

from orchestration import assets
from orchestration.schedules import JOBS, SCHEDULES


def _carregar_modulos_de_assets():
    """Descobre e carrega automaticamente todos os módulos em orchestration/assets/."""
    modulos = []
    for _, nome_modulo, is_pkg in pkgutil.iter_modules(assets.__path__):
        if not is_pkg and not nome_modulo.startswith("_"):
            mod = importlib.import_module(f"orchestration.assets.{nome_modulo}")
            modulos.append(mod)
    return modulos


_modulos = _carregar_modulos_de_assets()

defs = Definitions(
    assets=load_assets_from_modules(_modulos),
    asset_checks=load_asset_checks_from_modules(_modulos),
    jobs=JOBS,
    schedules=SCHEDULES,
)
