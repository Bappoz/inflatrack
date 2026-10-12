"""Gera os diagramas SVG da documentação em ``docs/assets/diagramas/``.

Uso::

    uv run python scripts/gerar_diagramas.py

Os diagramas são desenhados à mão (posição de cada caixa e rota de cada seta), em
vez de deixados para um layout automático, porque o objetivo é legibilidade. Cada
SVG é incluído *inline* na página (``--8<--``), então herda as cores do tema claro ou
escuro pelas variáveis ``--dg-*`` de ``docs/stylesheets/extra.css``; os valores depois
da vírgula em ``var(--dg-x, ...)`` valem quando o arquivo é aberto sozinho.

Colunas, tipos e chaves dos esquemas vêm de ``migrations/`` e ``scripts/setup_duckdb*.sql``:
ao mudar o DDL, atualize a tabela correspondente aqui e gere de novo.
"""

# ruff: noqa: E501 (as linhas longas são marcação SVG; quebrá-las piora a leitura)

from __future__ import annotations

from html import escape
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "docs" / "assets" / "diagramas"

ESTILO = """
.dg text{font-family:var(--inflatrack-font-body,Inter,system-ui,sans-serif)}
.dg .nome{font-size:13px;font-weight:600;fill:var(--dg-ink,#1A132F)}
.dg .col{font-size:12px;fill:var(--dg-ink,#1A132F)}
.dg .sub,.dg .tipo,.dg .rot,.dg .tag,.dg .zona-t{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.dg .sub{font-size:10px;fill:var(--dg-muted,#5B5675)}
.dg .tipo{font-size:10px;fill:var(--dg-muted,#5B5675)}
.dg .rot{font-size:9px;letter-spacing:.06em;fill:var(--dg-muted,#5B5675)}
.dg .tag{font-size:8px;font-weight:600;letter-spacing:.1em;fill:var(--dg-brand,#511EB6)}
.dg .zona-t{font-size:9px;font-weight:600;letter-spacing:.12em;fill:var(--dg-muted,#5B5675)}
.dg .papel{fill:var(--dg-paper,#FFFFFF)}
.dg .caixa{fill:var(--dg-surface,#FFFFFF);stroke:var(--dg-line,#8E86AD);stroke-width:1}
.dg .dep{fill:var(--dg-brand-tint,#F1EDFB);stroke:var(--dg-brand,#511EB6);stroke-width:1}
.dg .foco{fill:var(--dg-accent-tint,#FFEEE9);stroke:var(--dg-accent,#FF5A36);stroke-width:1.2}
.dg .ext{fill:var(--dg-zone,#F6F4FC);stroke:var(--dg-line,#8E86AD);stroke-width:1;stroke-dasharray:4 3}
.dg .zona{fill:var(--dg-zone,#F6F4FC);stroke:var(--dg-rule,#D9D3EC);stroke-width:1;stroke-dasharray:4 4}
.dg .cab{fill:var(--dg-brand-tint,#F1EDFB)}
.dg .cab-foco{fill:var(--dg-accent-tint,#FFEEE9)}
.dg .zebra{fill:var(--dg-zebra,#FAF9FE)}
.dg .fio{stroke:var(--dg-rule,#D9D3EC);stroke-width:1}
.dg .chip{fill:none;stroke:var(--dg-brand,#511EB6);stroke-width:.8;opacity:.7}
.dg .seta{fill:none;stroke:var(--dg-muted,#5B5675);stroke-width:1.2}
.dg .seta-foco{fill:none;stroke:var(--dg-accent,#FF5A36);stroke-width:1.4}
.dg .seta-leve{fill:none;stroke:var(--dg-muted,#5B5675);stroke-width:1.2;stroke-dasharray:5 4}
.dg .ponta{fill:var(--dg-muted,#5B5675)}
.dg .ponta-foco{fill:var(--dg-accent,#FF5A36)}
.dg .rot-foco{fill:var(--dg-accent,#FF5A36)}
"""

ALTURA_CABECALHO = 32
ALTURA_LINHA = 24
RAIO = 8


class Diagrama:
    """Acumula formas em duas camadas: setas atrás, caixas na frente."""

    def __init__(self, slug: str, largura: int, altura: int, titulo: str, descricao: str) -> None:
        self.slug, self.largura, self.altura = slug, largura, altura
        self.titulo, self.descricao = titulo, descricao
        self.fundo: list[str] = []
        self.setas: list[str] = []
        self.rotulos: list[str] = []
        self.caixas: list[str] = []
        self._linhas: dict[tuple[str, str], tuple[int, int, int]] = {}

    # --- primitivas ---------------------------------------------------------------

    def zona(self, x: int, y: int, w: int, h: int, rotulo: str) -> None:
        self.fundo.append(f'<rect class="zona" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>')
        self.fundo.append(f'<text class="zona-t" x="{x + 12}" y="{y + 18}">{escape(rotulo)}</text>')

    def no(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        nome: str,
        *subs: str,
        tipo: str = "caixa",
        tag: str | None = None,
        classe_nome: str = "nome",
    ) -> None:
        """Caixa com nome e até duas linhas técnicas; `tipo` é a classe de estilo."""
        cx = x + w // 2
        partes = [
            f'<rect class="papel" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>',
            f'<rect class="{tipo}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>',
        ]
        topo = y + 16 if tag else y
        if tag:
            partes.append(f'<text class="tag" x="{x + 10}" y="{y + 16}">{escape(tag)}</text>')
        subs = tuple(sub for sub in subs if sub)
        linhas = 1 + len(subs)
        base = topo + (y + h - topo) // 2 - (linhas - 1) * 7 + 4
        partes.append(
            f'<text class="{classe_nome}" x="{cx}" y="{base}" text-anchor="middle">{escape(nome)}</text>'
        )
        for indice, sub in enumerate(subs, start=1):
            partes.append(
                f'<text class="sub" x="{cx}" y="{base + indice * 15}" text-anchor="middle">{escape(sub)}</text>'
            )
        self.caixas.extend(partes)

    def seta(self, *pontos: tuple[int, int], tipo: str = "seta", ponta: bool = True) -> None:
        """Conector ortogonal pelos pontos dados, com cantos arredondados."""
        d = [f"M{pontos[0][0]},{pontos[0][1]}"]
        for anterior, atual, proximo in zip(pontos, pontos[1:], pontos[2:], strict=False):
            entrada = _rumo(anterior, atual)
            saida = _rumo(atual, proximo)
            antes = (atual[0] - entrada[0] * RAIO, atual[1] - entrada[1] * RAIO)
            depois = (atual[0] + saida[0] * RAIO, atual[1] + saida[1] * RAIO)
            d.append(f"L{antes[0]},{antes[1]} Q{atual[0]},{atual[1]} {depois[0]},{depois[1]}")
        d.append(f"L{pontos[-1][0]},{pontos[-1][1]}")
        marcador = "foco" if tipo == "seta-foco" else "normal"
        fim = f' marker-end="url(#{self.slug}-{marcador})"' if ponta else ""
        self.setas.append(f'<path class="{tipo}" d="{" ".join(d)}"{fim}/>')

    def rotulo(self, cx: int, y: int, texto: str, foco: bool = False) -> None:
        """Rótulo de seta: `y` é a linha de base; fica sobre uma máscara da cor do papel."""
        largura = len(texto) * 6 + 12
        classe = "rot rot-foco" if foco else "rot"
        self.rotulos.append(
            f'<rect class="papel" x="{cx - largura // 2}" y="{y - 10}" width="{largura}" height="14" rx="2"/>'
        )
        self.rotulos.append(
            f'<text class="{classe}" x="{cx}" y="{y}" text-anchor="middle">{escape(texto)}</text>'
        )

    def tabela(
        self,
        nome: str,
        x: int,
        y: int,
        w: int,
        colunas: list[tuple[str, str, str]],
        *,
        tag: str = "TABELA",
        foco: bool = False,
    ) -> int:
        """Tabela física: uma linha por coluna ``(nome, tipo SQL, chave)``. Devolve a altura."""
        h = ALTURA_CABECALHO + ALTURA_LINHA * len(colunas)
        partes = [
            f'<rect class="papel" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>',
            f'<clipPath id="{self.slug}-{nome}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/></clipPath>',
            f'<g clip-path="url(#{self.slug}-{nome})">',
            f'<rect class="{"cab-foco" if foco else "cab"}" x="{x}" y="{y}" width="{w}" height="{ALTURA_CABECALHO}"/>',
        ]
        for indice, (coluna, tipo, chave) in enumerate(colunas):
            topo = y + ALTURA_CABECALHO + indice * ALTURA_LINHA
            meio = topo + ALTURA_LINHA // 2
            self._linhas[(nome, coluna)] = (x, x + w, meio)
            if indice % 2:
                partes.append(
                    f'<rect class="zebra" x="{x}" y="{topo}" width="{w}" height="{ALTURA_LINHA}"/>'
                )
            if chave:
                partes.append(
                    f'<rect class="chip" x="{x + 10}" y="{meio - 7}" width="22" height="14" rx="2"/>'
                )
                partes.append(
                    f'<text class="tag" x="{x + 21}" y="{meio + 3}" text-anchor="middle">{chave}</text>'
                )
            partes.append(f'<text class="col" x="{x + 40}" y="{meio + 4}">{escape(coluna)}</text>')
            partes.append(
                f'<text class="tipo" x="{x + w - 12}" y="{meio + 4}" text-anchor="end">{escape(tipo)}</text>'
            )
        partes += [
            "</g>",
            f'<line class="fio" x1="{x}" y1="{y + ALTURA_CABECALHO}" x2="{x + w}" y2="{y + ALTURA_CABECALHO}"/>',
            f'<rect class="{"foco" if foco else "caixa"}" style="fill:none" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>',
            f'<text class="nome" x="{x + 12}" y="{y + 21}">{escape(nome)}</text>',
            f'<text class="tag" x="{x + w - 12}" y="{y + 20}" text-anchor="end">{tag}</text>',
        ]
        self.caixas.extend(partes)
        return h

    def linha(self, tabela: str, coluna: str, lado: str, desvio: int = 0) -> tuple[int, int]:
        """Ponto de ancoragem de uma FK: borda `lado` ("e" ou "d") da linha da coluna."""
        esquerda, direita, meio = self._linhas[(tabela, coluna)]
        return (esquerda if lado == "e" else direita, meio + desvio)

    def legenda(self, y: int, itens: list[tuple[str, str]]) -> None:
        """Faixa horizontal no rodapé: ``(classe da amostra, texto)``."""
        self.fundo.append(
            f'<line class="fio" x1="16" y1="{y - 16}" x2="{self.largura - 16}" y2="{y - 16}"/>'
        )
        x = 16
        for classe, texto in itens:
            if classe.startswith("seta"):
                marcador = "foco" if classe == "seta-foco" else "normal"
                self.fundo.append(
                    f'<path class="{classe}" d="M{x},{y - 4} L{x + 24},{y - 4}" marker-end="url(#{self.slug}-{marcador})"/>'
                )
            else:
                self.fundo.append(
                    f'<rect class="{classe}" x="{x}" y="{y - 11}" width="24" height="14" rx="3"/>'
                )
            self.fundo.append(f'<text class="sub" x="{x + 34}" y="{y}">{escape(texto)}</text>')
            x += 34 + len(texto) * 6 + 28

    # --- saída --------------------------------------------------------------------

    def svg(self) -> str:
        s = self.slug
        cabecalho = [
            f'<svg class="dg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.largura} {self.altura}" '
            f'width="{self.largura}" height="{self.altura}" '
            f'role="img" aria-labelledby="{s}-title {s}-desc">',
            f'<title id="{s}-title">{escape(self.titulo)}</title>',
            f'<desc id="{s}-desc">{escape(self.descricao)}</desc>',
            "<defs>",
            f"<style>{''.join(ESTILO.split(chr(10)))}</style>",
            f'<marker id="{s}-normal" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
            '<polygon class="ponta" points="0 0, 8 3, 0 6"/></marker>',
            f'<marker id="{s}-foco" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
            '<polygon class="ponta-foco" points="0 0, 8 3, 0 6"/></marker>',
            "</defs>",
        ]
        # Sem linha em branco: o Markdown encerraria o bloco HTML no meio do SVG.
        return (
            "\n".join([*cabecalho, *self.fundo, *self.setas, *self.rotulos, *self.caixas, "</svg>"])
            + "\n"
        )

    def gravar(self) -> None:
        DESTINO.mkdir(parents=True, exist_ok=True)
        (DESTINO / f"{self.slug}.svg").write_text(self.svg(), encoding="utf-8")


def _rumo(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))


# --- fluxos em camadas ---------------------------------------------------------------

LARGURA_FLUXO = 976
# As etapas ocupam sempre a faixa x = 204..768; com três, cada caixa fica mais larga.
POSICAO_ETAPAS = {4: ((204, 352, 500, 648), 120), 3: ((204, 408, 612), 156)}
X_CONSUMO, LARGURA_CONSUMO, X_CALHA = 796, 164, 782


def fluxo(
    slug: str,
    titulo: str,
    descricao: str,
    *,
    fontes: list[str],
    rotulo_fontes: str,
    legenda_fonte: str = "fonte externa",
    etapas: list[tuple[str, str, str, str]],
    consumidores: list[tuple[str, str]],
    postgres: tuple[str, str] | None = None,
    orquestrador: str | None = None,
    grupos: list[tuple[str, int, int]] | None = None,
) -> Diagrama:
    """Fontes -> quatro etapas -> consumidores, com Postgres e orquestrador opcionais.

    `etapas` são ``(tag, nome, linha técnica 1, linha técnica 2)``; a última é o foco.
    `grupos` desenha uma zona nomeada em volta das etapas ``[início, fim]``.
    """
    X_ETAPAS, LARGURA_ETAPA = POSICAO_ETAPAS[len(etapas)]
    topo = 40 if grupos else 16
    altura_fontes = 32 + len(fontes) * 32 + 4
    meio = topo + altura_fontes // 2
    y_etapa = meio - 40
    base = topo + altura_fontes
    y_rodape = base + 28
    altura = y_rodape + (56 if orquestrador or postgres else -12) + 44
    d = Diagrama(slug, LARGURA_FLUXO, altura, titulo, descricao)

    d.zona(16, topo, 160, altura_fontes, rotulo_fontes)
    for indice, fonte in enumerate(fontes):
        d.no(28, topo + 30 + indice * 32, 136, 24, fonte, tipo="ext", classe_nome="col")
    for rotulo, inicio, fim in grupos or []:
        x = X_ETAPAS[inicio] - 12
        d.zona(x, y_etapa - 32, X_ETAPAS[fim] + LARGURA_ETAPA + 8 - x, 80 + 44, rotulo)

    d.seta((176, meio), (X_ETAPAS[0], meio))
    for indice, (tag, nome, sub1, sub2) in enumerate(etapas):
        ultima = indice == len(etapas) - 1
        d.no(
            X_ETAPAS[indice],
            y_etapa,
            LARGURA_ETAPA,
            80,
            nome,
            sub1,
            sub2,
            tag=tag,
            tipo="foco" if ultima else "dep",
        )
        if not ultima:
            d.seta((X_ETAPAS[indice] + LARGURA_ETAPA, meio), (X_ETAPAS[indice + 1], meio))

    direita = X_ETAPAS[-1] + LARGURA_ETAPA
    if len(consumidores) == 1:
        d.seta((direita, meio), (X_CONSUMO, meio), tipo="seta-foco")
        d.no(X_CONSUMO, meio - 28, LARGURA_CONSUMO, 56, *consumidores[0])
        y_ultimo = meio + 28
    else:
        # Duas saídas da mesma borda: pontos de ancoragem separados. A calha é a mesma,
        # mas uma sobe e a outra desce, então os traços nunca se sobrepõem.
        cima, baixo = meio - 64, meio + 32
        d.seta(
            (direita, meio - 12),
            (X_CALHA, meio - 12),
            (X_CALHA, cima + 28),
            (X_CONSUMO, cima + 28),
            tipo="seta-foco",
        )
        d.seta(
            (direita, meio + 12),
            (X_CALHA, meio + 12),
            (X_CALHA, baixo + 28),
            (X_CONSUMO, baixo + 28),
            tipo="seta-foco",
        )
        d.no(X_CONSUMO, cima, LARGURA_CONSUMO, 56, *consumidores[0])
        d.no(X_CONSUMO, baixo, LARGURA_CONSUMO, 56, *consumidores[1])
        y_ultimo = baixo + 56

    if postgres:
        d.no(X_CONSUMO, y_rodape, LARGURA_CONSUMO, 56, *postgres, tipo="caixa", tag="OLTP")
        d.seta((X_CONSUMO + 82, y_rodape), (X_CONSUMO + 82, y_ultimo), tipo="seta-leve")
    if orquestrador:
        d.no(X_ETAPAS[0], y_rodape + 8, direita - X_ETAPAS[0], 40, orquestrador, tipo="caixa")
        for x in X_ETAPAS:
            d.seta(
                (x + LARGURA_ETAPA // 2, y_rodape + 8),
                (x + LARGURA_ETAPA // 2, y_etapa + 80),
                tipo="seta-leve",
            )

    legenda = [("ext", legenda_fonte), ("dep", "camada"), ("foco", "camada de consumo")]
    if orquestrador or postgres:
        legenda.append(
            (
                "seta-leve",
                "orquestra / lê em paralelo"
                if orquestrador and postgres
                else "orquestra"
                if orquestrador
                else "lê em paralelo",
            )
        )
    d.legenda(altura - 12, legenda)
    return d


CAMADAS = [
    ("RAW", "Raw", "data/raw/<fonte>/", "json.gz · html.gz"),
    ("BRONZE", "Bronze", "data/parquet/", "<fonte>/ · Parquet"),
    ("SILVER", "Silver", "dbt-duckdb", "models/staging/"),
    ("GOLD", "Gold", "DuckDB · fato,", "dimensão e features"),
]


def diagramas_de_fluxo() -> list[Diagrama]:
    return [
        fluxo(
            "fluxo-dados",
            "Fluxo de dados do InflaTrack",
            "Seis provedores públicos alimentam as camadas Raw, Bronze, Silver e Gold; a Gold serve "
            "notebooks e o painel, que também lê o PostgreSQL transacional. O Dagster orquestra as quatro camadas.",
            fontes=[
                "SIDRA / IBGE",
                "BCB (Olinda, SGS)",
                "Alpha Vantage",
                "Banco Mundial",
                "DIEESE",
                "INMET",
            ],
            rotulo_fontes="FONTES",
            etapas=CAMADAS,
            consumidores=[("Notebooks", "MLflow"), ("Streamlit", "Plotly")],
            postgres=("PostgreSQL", "lojista, produto, reajuste"),
            orquestrador="Dagster",
        ),
        fluxo(
            "medallion",
            "Arquitetura Medallion do InflaTrack",
            "As oito fontes públicas passam por Raw, Bronze, Silver e Gold; a Gold serve notebooks e o painel, "
            "que lê o PostgreSQL transacional em paralelo. O Dagster orquestra as quatro camadas.",
            fontes=[
                "IPCA / INPC",
                "Dólar",
                "Selic",
                "Commodities",
                "PIB",
                "PIB da China",
                "Salário mínimo",
                "Clima",
            ],
            rotulo_fontes="8 FONTES PÚBLICAS",
            etapas=[
                ("RAW", "Raw", "resposta original", "json.gz"),
                ("BRONZE", "Bronze", "tipada, sem regra", "Parquet"),
                ("SILVER", "Silver", "limpa e conformada", "dbt-duckdb"),
                ("GOLD", "Gold", "pronta para consumo", "tabelas no DuckDB"),
            ],
            consumidores=[("Notebooks", "MLflow"), ("Streamlit", "Plotly")],
            postgres=("PostgreSQL", "transacional"),
            orquestrador="Dagster",
        ),
        fluxo(
            "dicionario-visao-geral",
            "Onde vive cada conjunto de dados",
            "Sete grupos de fontes passam por Raw, Bronze, Silver e Gold até o painel e os modelos; "
            "o PostgreSQL transacional alimenta o painel diretamente.",
            fontes=[
                "SIDRA · IPCA/INPC",
                "BCB · Dólar e Selic",
                "Alpha Vantage",
                "SIDRA 1846 · PIB",
                "World Bank",
                "DIEESE",
                "INMET · Clima",
            ],
            rotulo_fontes="FONTES",
            etapas=[
                ("RAW", "Raw", "resposta original", ""),
                ("BRONZE", "Bronze", "Parquet", ""),
                ("SILVER", "Silver", "staging", ""),
                ("GOLD", "Gold", "fato e dimensão", ""),
            ],
            consumidores=[("Painel + Modelos", "consumo")],
            postgres=("PostgreSQL", "lojista, produto, reajuste"),
        ),
        fluxo(
            "orquestracao-assets",
            "Grafo de assets do Dagster",
            "Seis assets de ingestão em Python alimentam o asset Bronze de cada fonte; os assets dbt produzem "
            "a Silver e a Gold, de onde saem a matriz de treino e a cópia publicada para o Streamlit.",
            fontes=[
                "raw_sidra",
                "raw_bcb",
                "raw_alphavantage",
                "raw_worldbank",
                "raw_dieese",
                "raw_inmet",
            ],
            rotulo_fontes="INGESTÃO (PYTHON)",
            legenda_fonte="asset de ingestão",
            etapas=[
                ("BRONZE", "bronze_<fonte>", "Parquet", ""),
                ("SILVER", "stg_<fonte>", "staging", ""),
                ("GOLD", "fato, dimensão", "features", ""),
            ],
            consumidores=[
                ("matriz_treino", "modelos"),
                ("gold_publicada", "cópia para o Streamlit"),
            ],
            grupos=[("ASSET BRONZE", 0, 0), ("ASSETS DBT (DAGSTER-DBT)", 1, 2)],
        ),
    ]


# --- esquemas físicos ------------------------------------------------------------------

Coluna = tuple[str, str, str]


def largura_da_tabela(nome: str, colunas: list[Coluna]) -> int:
    """Largura que acomoda o maior nome de coluna e o maior tipo, em múltiplos de 8."""
    conteudo = (
        max(len(coluna) for coluna, _, _ in colunas) * 7
        + max(len(tipo) for _, tipo, _ in colunas) * 6
    )
    return max(conteudo + 76, len(nome) * 8 + 96) // 8 * 8 + 8


def esquema_simples(
    slug: str,
    titulo: str,
    descricao: str,
    tabelas: list[tuple[str, list[Coluna]]],
    fk: tuple[str, str, str] | None = None,
    tag: str = "DUCKDB",
) -> Diagrama:
    """Uma ou duas tabelas lado a lado. `fk` = (coluna filha, coluna pai, texto da legenda).

    A tabela pai vem primeiro; a FK liga a primeira linha das duas, por isso sai reta.
    """
    larguras = [largura_da_tabela(nome, colunas) for nome, colunas in tabelas]
    vao = 96 if fk else 40
    altura_tabelas = max(ALTURA_CABECALHO + ALTURA_LINHA * len(colunas) for _, colunas in tabelas)
    largura = 32 + sum(larguras) + vao * (len(tabelas) - 1)
    altura = 16 + altura_tabelas + (60 if fk else 16)
    d = Diagrama(slug, largura, altura, titulo, descricao)
    x = 16
    for (nome, colunas), w in zip(tabelas, larguras, strict=True):
        d.tabela(nome, x, 16, w, colunas, tag=tag)
        x += w + vao
    if fk:
        filha, pai, texto = fk
        declarada = "sem FK" not in texto
        d.seta(
            d.linha(tabelas[1][0], filha, "e"),
            d.linha(tabelas[0][0], pai, "d"),
            tipo="seta" if declarada else "seta-leve",
        )
        d.legenda(altura - 12, [("seta" if declarada else "seta-leve", texto)])
    return d


def esquema_sidra() -> Diagrama:
    d = Diagrama(
        "esquema-sidra",
        912,
        596,
        "Esquema físico do IPCA/INPC no PostgreSQL",
        "A tabela de fato observacao referencia fonte_agregado, classificacao, localidade e variavel; "
        "classificacao_versao guarda o nome de cada código por fonte e vigência.",
    )
    d.tabela(
        "fonte_agregado",
        56,
        16,
        232,
        [
            ("id", "smallint", "PK"),
            ("indice", "text", ""),
            ("nome", "text", ""),
            ("periodo_inicio", "date", ""),
            ("periodo_fim", "date", ""),
            ("tem_acum_12m", "boolean", ""),
        ],
        tag="REFERÊNCIA",
    )
    d.tabela(
        "classificacao",
        56,
        224,
        232,
        [("codigo", "text", "PK"), ("nivel", "text", "")],
        tag="REFERÊNCIA",
    )
    d.tabela(
        "classificacao_versao",
        56,
        336,
        232,
        [
            ("id", "bigint", "PK"),
            ("codigo", "text", "FK"),
            ("id_fonte", "smallint", "FK"),
            ("nome", "text", ""),
            ("codigo_pai", "text", "FK"),
            ("vigencia_inicio", "date", ""),
            ("vigencia_fim", "date", ""),
        ],
        tag="DIMENSÃO SCD2",
    )
    d.tabela(
        "observacao",
        368,
        104,
        256,
        [
            ("id", "bigint", "PK"),
            ("id_fonte", "smallint", "FK"),
            ("codigo_classificacao", "text", "FK"),
            ("codigo_localidade", "integer", "FK"),
            ("codigo_variavel", "smallint", "FK"),
            ("mes_referencia", "date", ""),
            ("valor", "numeric(16,7)", ""),
            ("ingerido_em", "timestamptz", ""),
        ],
        tag="FATO · INSERT-ONLY",
        foco=True,
    )
    d.tabela(
        "localidade",
        696,
        40,
        200,
        [
            ("codigo_ibge", "integer", "PK"),
            ("nome", "text", ""),
            ("tipo", "text", ""),
            ("uf", "char(2)", ""),
        ],
        tag="REFERÊNCIA",
    )
    d.tabela(
        "variavel",
        696,
        232,
        200,
        [("codigo", "smallint", "PK"), ("nome", "text", ""), ("unidade", "text", "")],
        tag="REFERÊNCIA",
    )

    def ligar(origem: tuple[int, int], destino: tuple[int, int], calha: int) -> None:
        d.seta(origem, (calha, origem[1]), (calha, destino[1]), destino)

    # Duas FKs chegam na mesma linha de fonte_agregado e de classificacao, por bordas opostas.
    ligar(d.linha("observacao", "id_fonte", "e"), d.linha("fonte_agregado", "id", "d"), 328)
    ligar(
        d.linha("observacao", "codigo_classificacao", "e"),
        d.linha("classificacao", "codigo", "d"),
        312,
    )
    ligar(
        d.linha("classificacao_versao", "codigo", "e"), d.linha("classificacao", "codigo", "e"), 40
    )
    ligar(
        d.linha("classificacao_versao", "id_fonte", "e"), d.linha("fonte_agregado", "id", "e"), 24
    )
    ligar(
        d.linha("observacao", "codigo_localidade", "d"),
        d.linha("localidade", "codigo_ibge", "e"),
        656,
    )
    ligar(d.linha("observacao", "codigo_variavel", "d"), d.linha("variavel", "codigo", "e"), 672)
    d.legenda(584, [("seta", "FK com ON DELETE RESTRICT"), ("cab-foco", "tabela de fato")])
    return d


def esquema_transacional() -> Diagrama:
    d = Diagrama(
        "esquema-transacional",
        960,
        452,
        "Esquema físico do banco transacional do lojista",
        "Um lojista tem produtos e cada produto tem um histórico de reajustes, apagados em cascata; "
        "lojista e produto apontam para a localidade e a classificação de referência do IPCA.",
    )
    d.tabela("localidade", 40, 16, 240, [("codigo_ibge", "integer", "PK")], tag="REFERÊNCIA IPCA")
    d.tabela(
        "lojista",
        40,
        96,
        240,
        [
            ("id", "bigint", "PK"),
            ("nome_fantasia", "text", ""),
            ("cnpj", "char(14)", "UQ"),
            ("codigo_localidade", "integer", "FK"),
            ("codigo_grupo_ipca", "text", "FK"),
            ("criado_em", "timestamptz", ""),
        ],
    )
    d.tabela(
        "classificacao",
        40,
        312,
        240,
        [("codigo", "text", "PK"), ("nivel", "text", "")],
        tag="REFERÊNCIA IPCA",
    )
    d.tabela(
        "produto",
        344,
        16,
        264,
        [
            ("id", "bigint", "PK"),
            ("id_lojista", "bigint", "FK"),
            ("nome", "text", ""),
            ("preco_inicial_centavos", "integer", ""),
            ("custo_inicial_centavos", "integer", ""),
            ("codigo_subitem_ipca", "text", "FK"),
            ("criado_em", "timestamptz", ""),
        ],
    )
    d.tabela(
        "reajuste",
        672,
        16,
        272,
        [
            ("id", "bigint", "PK"),
            ("id_produto", "bigint", "FK"),
            ("preco_anterior_centavos", "integer", ""),
            ("preco_novo_centavos", "integer", ""),
            ("ipca_acumulado_ref", "numeric(8,4)", ""),
            ("mes_referencia_ipca", "date", ""),
            ("motivo", "text", ""),
            ("aplicado_em", "timestamptz", ""),
        ],
    )

    def ligar(
        origem: tuple[int, int], destino: tuple[int, int], calha: int, tipo: str = "seta"
    ) -> None:
        d.seta(origem, (calha, origem[1]), (calha, destino[1]), destino, tipo=tipo)

    ligar(d.linha("produto", "id_lojista", "e"), d.linha("lojista", "id", "d"), 312, "seta-foco")
    ligar(d.linha("reajuste", "id_produto", "e"), d.linha("produto", "id", "d"), 640, "seta-foco")
    ligar(
        d.linha("lojista", "codigo_localidade", "e"), d.linha("localidade", "codigo_ibge", "e"), 20
    )
    ligar(
        d.linha("lojista", "codigo_grupo_ipca", "d"),
        d.linha("classificacao", "codigo", "d", -8),
        296,
    )
    ligar(
        d.linha("produto", "codigo_subitem_ipca", "e"),
        d.linha("classificacao", "codigo", "d", 8),
        320,
    )
    d.legenda(440, [("seta-foco", "ON DELETE CASCADE"), ("seta", "ON DELETE RESTRICT")])
    return d


def diagramas_de_esquema() -> list[Diagrama]:
    return [
        esquema_sidra(),
        esquema_transacional(),
        esquema_simples(
            "esquema-commodities",
            "Esquema físico das commodities no DuckDB",
            "Cada commodity do cadastro tem uma cotação por data de referência.",
            [
                (
                    "commodity",
                    [
                        ("symbol", "VARCHAR", "PK"),
                        ("name", "VARCHAR", ""),
                        ("category", "VARCHAR", ""),
                        ("unit", "VARCHAR", ""),
                    ],
                ),
                (
                    "commodity_cotacao",
                    [
                        ("symbol", "VARCHAR", "PK"),
                        ("data_referencia", "DATE", "PK"),
                        ("preco", "DOUBLE", ""),
                    ],
                ),
            ],
            fk=("symbol", "symbol", "FK declarada: commodity_cotacao.symbol → commodity.symbol"),
        ),
        esquema_simples(
            "esquema-pib",
            "Esquema físico do PIB no DuckDB",
            "Cada setor das contas nacionais tem um valor por trimestre.",
            [
                (
                    "pib_setor",
                    [
                        ("codigo", "VARCHAR", "PK"),
                        ("nome", "VARCHAR", ""),
                        ("grupo", "VARCHAR", ""),
                        ("nucleo", "BOOLEAN", ""),
                    ],
                ),
                (
                    "pib_valor",
                    [
                        ("codigo_setor", "VARCHAR", "PK"),
                        ("data_referencia", "DATE", "PK"),
                        ("ano", "SMALLINT", ""),
                        ("trimestre", "TINYINT", ""),
                        ("valor_milhoes_brl", "DOUBLE", ""),
                    ],
                ),
            ],
            fk=(
                "codigo_setor",
                "codigo",
                "FK declarada: pib_valor.codigo_setor → pib_setor.codigo",
            ),
        ),
        esquema_simples(
            "esquema-clima",
            "Esquema físico do clima no DuckDB",
            "Cada estação meteorológica registra uma linha de clima por dia.",
            [
                (
                    "estacao_meteorologica",
                    [
                        ("estacao_id", "VARCHAR(10)", "PK"),
                        ("nome", "VARCHAR", ""),
                        ("estado", "VARCHAR(2)", ""),
                        ("tipo", "VARCHAR(20)", ""),
                        ("latitude", "DOUBLE", ""),
                        ("longitude", "DOUBLE", ""),
                        ("altitude_m", "DOUBLE", ""),
                        ("situacao", "VARCHAR(20)", ""),
                        ("atualizado_em", "TIMESTAMP", ""),
                    ],
                ),
                (
                    "clima_diario",
                    [
                        ("estacao_id", "VARCHAR(10)", "PK"),
                        ("data_referencia", "DATE", "PK"),
                        ("temp_min", "DOUBLE", ""),
                        ("temp_max", "DOUBLE", ""),
                        ("temp_media", "DOUBLE", ""),
                        ("precipitacao_total_mm", "DOUBLE", ""),
                        ("umidade_relativa_media_pct", "DOUBLE", ""),
                        ("umidade_relativa_min_pct", "DOUBLE", ""),
                        ("observado", "BOOLEAN", ""),
                        ("atualizado_em", "TIMESTAMP", ""),
                    ],
                ),
            ],
            fk=(
                "estacao_id",
                "estacao_id",
                "relação lógica por estacao_id (sem FK declarada no DDL)",
            ),
        ),
        esquema_simples(
            "esquema-macroeconomia",
            "Esquema físico do dólar e da Selic no DuckDB",
            "Duas séries diárias independentes, uma linha por data de referência em cada tabela.",
            [
                (
                    "dolar_cotacao",
                    [
                        ("data_referencia", "DATE", "PK"),
                        ("cotacao_compra", "DOUBLE", ""),
                        ("cotacao_venda", "DOUBLE", ""),
                        ("observado", "BOOLEAN", ""),
                    ],
                ),
                (
                    "selic_taxa",
                    [
                        ("data_referencia", "DATE", "PK"),
                        ("taxa_dia_pct", "DOUBLE", ""),
                        ("observado", "BOOLEAN", ""),
                    ],
                ),
            ],
        ),
        esquema_simples(
            "esquema-pib-china",
            "Esquema físico do PIB da China no DuckDB",
            "Uma linha por ano, com crescimento percentual e PIB em dólares.",
            [
                (
                    "pib_china",
                    [
                        ("ano", "SMALLINT", "PK"),
                        ("crescimento_pib_pct", "DOUBLE", ""),
                        ("pib_usd", "DOUBLE", ""),
                        ("atualizado_em", "TIMESTAMP", ""),
                    ],
                )
            ],
        ),
        esquema_simples(
            "esquema-salario-minimo",
            "Esquema físico do salário mínimo no DuckDB",
            "Uma linha por mês, com o salário nominal, o necessário e a razão entre os dois.",
            [
                (
                    "salario_minimo",
                    [
                        ("ano_mes", "VARCHAR(7)", "PK"),
                        ("data_referencia", "DATE", ""),
                        ("ano", "SMALLINT", ""),
                        ("mes", "TINYINT", ""),
                        ("salario_nominal", "DOUBLE", ""),
                        ("salario_necessario", "DOUBLE", ""),
                        ("multiplo_necessario_nominal", "DOUBLE", ""),
                        ("atualizado_em", "TIMESTAMP", ""),
                    ],
                )
            ],
        ),
    ]


def main() -> None:
    for diagrama in [*diagramas_de_fluxo(), *diagramas_de_esquema()]:
        diagrama.gravar()
        print(f"{diagrama.slug}.svg  {diagrama.largura}x{diagrama.altura}")


if __name__ == "__main__":
    main()
