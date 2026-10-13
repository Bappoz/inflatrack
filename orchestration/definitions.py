"""Ponto de entrada do Dagster: `uv run dagster dev` (ou `just orquestrador`).

Carrega todo módulo de `orchestration/assets/`: cada fonte cria o seu sem mexer nos outros.
"""

from dagster import Definitions, load_assets_from_package_module

from orchestration import assets
from orchestration.schedules import JOBS, SCHEDULES

defs = Definitions(
    assets=load_assets_from_package_module(assets),
    jobs=JOBS,
    schedules=SCHEDULES,
)
