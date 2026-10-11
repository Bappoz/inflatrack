"""Ponto de entrada do Dagster: `uv run dagster dev` (ou `just orquestrador`)."""

from dagster import Definitions, load_assets_from_modules

from orchestration.assets import ingestao
from orchestration.schedules import JOBS, SCHEDULES

defs = Definitions(
    assets=load_assets_from_modules([ingestao]),
    jobs=JOBS,
    schedules=SCHEDULES,
)
