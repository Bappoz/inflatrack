"""Catálogo da tabela 1846 do SIDRA — Contas Nacionais Trimestrais.

<https://sidra.ibge.gov.br/tabela/1846> — *Valores a preços correntes*, em
milhões de reais, trimestral, de 1996T1 em diante, só Brasil (N1).

Fatos medidos em 2026-09-25 que moldam este módulo:

* A tabela tem **uma única variável** (585, valores a preços correntes) e
  **23 categorias** na classificação ``c11255`` (setores e subsetores). Um ano
  inteiro são 4 x 23 = 92 valores — três ordens de grandeza abaixo do teto de
  50.000 da API. A paginação anual aqui é escolha de organização da camada
  crua, não imposição da origem como no IPCA (ver :mod:`inflatrack.sidra`).
* O período vem como ``AAAATT`` (``199601`` = 1º trimestre de 1996), e **não**
  como ``AAAAMM``. Reaproveitar ``ingest.mes_para_data`` daria janeiro de 1996
  para o 1T e fevereiro para o 2T — erro silencioso.
* As 23 categorias misturam três coisas que não se somam entre si: valor
  adicionado por atividade, componentes da demanda e agregados (PIB, impostos).
  Somar tudo dá número sem significado; daí a coluna ``grupo``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

AGREGADO = 1846
VARIAVEL = 585
CLASSIFICACAO = "11255"
NIVEIS = "n1/all"
UNIDADE = "Milhões de Reais"

# Como cada categoria entra na conta. Ver o docstring do módulo: as três
# famílias não se somam entre si.
GRUPO_ATIVIDADE = "atividade"  # valor adicionado do setor
GRUPO_DEMANDA = "demanda"  # ótica da despesa
GRUPO_AGREGADO = "agregado"  # totais (PIB, VA, impostos)

GRUPOS: dict[str, str] = {
    "90687": GRUPO_ATIVIDADE,  # Agropecuária - total
    "90691": GRUPO_ATIVIDADE,  # Indústria - total
    "90692": GRUPO_ATIVIDADE,  # Indústrias extrativas
    "90693": GRUPO_ATIVIDADE,  # Indústrias de transformação
    "90694": GRUPO_ATIVIDADE,  # Construção
    "90695": GRUPO_ATIVIDADE,  # Eletricidade e gás, água, esgoto, resíduos
    "90696": GRUPO_ATIVIDADE,  # Serviços - total
    "90697": GRUPO_ATIVIDADE,  # Comércio
    "90698": GRUPO_ATIVIDADE,  # Transporte, armazenagem e correio
    "90699": GRUPO_ATIVIDADE,  # Informação e comunicação
    "90700": GRUPO_ATIVIDADE,  # Atividades financeiras e de seguros
    "90701": GRUPO_ATIVIDADE,  # Outras atividades de serviços
    "90702": GRUPO_ATIVIDADE,  # Atividades imobiliárias
    "90703": GRUPO_ATIVIDADE,  # Administração, saúde e educação públicas
    "90705": GRUPO_AGREGADO,  # Valor adicionado a preços básicos
    "90706": GRUPO_AGREGADO,  # Impostos líquidos sobre produtos
    "90707": GRUPO_AGREGADO,  # PIB a preços de mercado
    "93404": GRUPO_DEMANDA,  # Despesa de consumo das famílias
    "93405": GRUPO_DEMANDA,  # Despesa de consumo da administração pública
    "93406": GRUPO_DEMANDA,  # Formação bruta de capital fixo
    "93407": GRUPO_DEMANDA,  # Exportação de bens e serviços
    "93408": GRUPO_DEMANDA,  # Importação de bens e serviços (-)
    "102880": GRUPO_DEMANDA,  # Variação de estoque
}

# Os indicadores com efeito mais direto no preço ao consumidor — o recorte que
# alimenta `vw_pib_nucleo`. As outras 11 categorias são baixadas junto (custam
# zero requisição a mais) e ficam disponíveis para análise posterior.
NUCLEO: frozenset[str] = frozenset(
    {
        "90687",  # Agropecuária: custo do alimento na origem
        "90695",  # Eletricidade e gás: custo de energia embutido em tudo
        "90696",  # Serviços - total
        "90697",  # Comércio: a margem do próprio lojista
        "90698",  # Transporte: frete até a prateleira
        "90700",  # Atividades financeiras: custo do capital de giro
        "90706",  # Impostos líquidos sobre produtos: carga sobre o preço final
        "90707",  # PIB a preços de mercado: denominador de tudo
        "93404",  # Despesa de consumo das famílias: a demanda
        "93405",  # Despesa de consumo da administração pública
        "93407",  # Exportação: concorre com o abastecimento interno
        "93408",  # Importação: o repasse do câmbio
    }
)


def trimestres(ano_inicio: int, ano_fim: int) -> Iterator[str]:
    """Gera períodos ``AAAATT`` de ``ano_inicio`` a ``ano_fim``, inclusive."""
    for ano in range(ano_inicio, ano_fim + 1):
        for trimestre in range(1, 5):
            yield f"{ano}{trimestre:02d}"


def periodo_do_ano(ano: int) -> str:
    """Intervalo aceito pela API para o ano inteiro: ``"199601-199604"``."""
    return f"{ano}01-{ano}04"


def trimestre_para_data(periodo: str) -> date:
    """``"199603"`` -> ``date(1996, 7, 1)`` — primeiro dia do 3º trimestre.

    Levanta ``ValueError`` para trimestre fora de 1..4, que é o sintoma de ter
    passado um período ``AAAAMM`` por engano.
    """
    ano, trimestre = int(periodo[:4]), int(periodo[4:])
    if not 1 <= trimestre <= 4:
        raise ValueError(f"trimestre inválido em {periodo!r}: esperado AAAATT com TT em 01..04")
    return date(ano, trimestre * 3 - 2, 1)


def setores(metadados: dict) -> list[tuple[str, str, str, bool]]:
    """Extrai ``(codigo, nome, grupo, nucleo)`` da classificação ``c11255``.

    Diferente da classificação 315 do IPCA, aqui o rótulo não vem colado a um
    código natural (``"1101002.Arroz"``): o nome vem limpo e o identificador é
    o ``id`` interno do SIDRA, que é o mesmo devolvido em ``D4C``.
    """
    saida: list[tuple[str, str, str, bool]] = []
    for classificacao in metadados.get("classificacoes", []):
        if str(classificacao.get("id")) != CLASSIFICACAO:
            continue
        for categoria in classificacao["categorias"]:
            codigo = str(categoria["id"])
            nome = str(categoria["nome"]).strip()
            saida.append((codigo, nome, GRUPOS.get(codigo, GRUPO_AGREGADO), codigo in NUCLEO))
    if not saida:
        raise ValueError(f"classificação c{CLASSIFICACAO} ausente nos metadados do {AGREGADO}")
    return saida
