"""Ativo dos preços de atacadista: a tabela de preços vai direto para o Postgres (ADR 0004).

Fica no Dagster só para a carga ser disparada junto com as outras fontes. O preço não passa por
Raw, Bronze, Silver nem Gold: o ativo não tem dependentes, nenhum job analítico o seleciona, e
`tests/orchestration/test_atacado.py` falha se alguém ligar um modelo do dbt ou uma carga do
DuckDB a ele. Reimportar não duplica nada, então rodar todo dia só pega o que mudou no arquivo.
"""

from dagster import AssetExecutionContext, asset

from inflatrack.atacado import importar_tabela
from orchestration.assets.comum import RETRY_REDE, executar

# O atacadista fictício de exemplo (o mesmo de `just atacado-importar` sem argumentos).
ARGUMENTOS = (
    "--arquivo",
    "data/atacado/tabela_exemplo.csv",
    "--fornecedor",
    "Atacadista Exemplo",
    "--ficticio",
)


@asset(
    group_name="atacado",
    retry_policy=RETRY_REDE,
    kinds={"python", "postgres"},
    description="Tabela de preços do atacadista no schema atacado do Postgres (fora do CDC).",
)
def atacado_postgres(context: AssetExecutionContext) -> None:
    executar(context, importar_tabela.main, *ARGUMENTOS)
