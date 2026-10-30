"""Cria ou atualiza o painel do Metabase a partir do que está versionado no Git.

O Metabase gratuito não exporta perguntas e dashboards para arquivo (a "serialization" é
paga). Então o painel mora em ``scripts/sql/metabase/``: um ``.sql`` por pergunta e o
``painel.toml``, que diz título, gráfico e posição de cada uma. Este script lê esses
arquivos e conversa com a API do Metabase:

1. Se o Metabase acabou de subir e nunca foi configurado, faz a configuração inicial com o
   login do ``.env`` (``METABASE_EMAIL`` e ``METABASE_SENHA``). Se já foi, entra com ele.
2. Cria a conexão com o Postgres, se ainda não existir. O Metabase lê só o Postgres.
3. Cria a coleção, cria ou atualiza cada pergunta (casando pelo título) e monta o dashboard.

Rodar de novo não duplica nada. Uso::

    docker compose --profile bi up -d
    uv run python scripts/metabase_painel.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger("metabase_painel")

PASTA_PAINEL = Path(__file__).resolve().parent / "sql" / "metabase"


# --- O que está no Git ---------------------------------------------------------------


@dataclass(frozen=True)
class Pergunta:
    titulo: str
    descricao: str
    banco: str
    sql: str
    grafico: str
    eixo_x: str | None
    eixo_y: list[str]
    linha: int
    coluna: int
    largura: int
    altura: int


@dataclass(frozen=True)
class Painel:
    nome: str
    colecao: str
    descricao: str
    bancos: dict[str, dict[str, Any]]
    perguntas: list[Pergunta]


def ler_painel(pasta: Path = PASTA_PAINEL) -> Painel:
    config = tomllib.loads((pasta / "painel.toml").read_text(encoding="utf-8"))
    perguntas = []
    for item in config.get("perguntas", []):
        if item["banco"] not in config["bancos"]:
            raise ValueError(f"{item['arquivo']}: banco {item['banco']!r} não está em [bancos]")
        posicao = item["posicao"]
        perguntas.append(
            Pergunta(
                titulo=item["titulo"],
                descricao=item.get("descricao", ""),
                banco=item["banco"],
                sql=(pasta / item["arquivo"]).read_text(encoding="utf-8"),
                grafico=item.get("grafico", "table"),
                eixo_x=item.get("eixo_x"),
                eixo_y=list(item.get("eixo_y", [])),
                linha=posicao["linha"],
                coluna=posicao["coluna"],
                largura=posicao["largura"],
                altura=posicao["altura"],
            )
        )
    painel = config["painel"]
    return Painel(painel["nome"], painel["colecao"], painel.get("descricao", ""),
                  config["bancos"], perguntas)  # fmt: skip


def detalhes_do_banco(banco: dict[str, Any]) -> dict[str, Any]:
    """O que o Metabase precisa para conectar. Credenciais saem do .env, nunca do Git."""
    if banco["engine"] == "postgres":
        return {
            "host": "db",  # nome do serviço no docker-compose
            "port": 5432,
            "dbname": os.environ.get("POSTGRES_DB", "inflatrack"),
            "user": os.environ.get("POSTGRES_USER", "inflatrack"),
            "password": os.environ.get("POSTGRES_PASSWORD", "inflatrack"),
            "ssl": False,
        }
    # Só Postgres: conectar o Metabase ao arquivo do DuckDB trava o dbt e os loaders.
    raise ValueError(f"engine não suportado: {banco['engine']} (o Metabase lê só o Postgres)")


def mesmo_destino(existente: dict[str, Any], banco: dict[str, Any]) -> bool:
    """A conexão já cadastrada no Metabase aponta para o banco que o painel quer?"""
    if existente.get("engine") != banco["engine"]:
        return False
    atual, desejado = existente.get("details") or {}, detalhes_do_banco(banco)
    return (atual.get("host"), atual.get("dbname")) == (desejado["host"], desejado["dbname"])


def corpo_da_pergunta(pergunta: Pergunta, id_banco: int, id_colecao: int) -> dict[str, Any]:
    visual: dict[str, Any] = {}
    if pergunta.eixo_x:
        visual["graph.dimensions"] = [pergunta.eixo_x]
    if pergunta.eixo_y:
        visual["graph.metrics"] = pergunta.eixo_y
    return {
        "name": pergunta.titulo,
        "description": pergunta.descricao or None,
        "collection_id": id_colecao,
        "display": pergunta.grafico,
        "visualization_settings": visual,
        "dataset_query": {
            "type": "native",
            "database": id_banco,
            "native": {"query": pergunta.sql},
        },
    }


# --- O que está no Metabase ---------------------------------------------------------


class Metabase:
    def __init__(self, url: str, cliente: httpx.Client | None = None) -> None:
        self.cliente = cliente or httpx.Client(base_url=url, timeout=60)

    def _pedir(self, metodo: str, caminho: str, **kwargs) -> Any:
        resposta = self.cliente.request(metodo, caminho, **kwargs)
        if resposta.is_error:
            raise RuntimeError(
                f"{metodo} {caminho}: HTTP {resposta.status_code} {resposta.text[:300]}"
            )
        return resposta.json() if resposta.content else None

    def esperar_subir(self, tentativas: int = 30) -> None:
        for _ in range(tentativas):
            try:
                if self.cliente.get("/api/health").json().get("status") == "ok":
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(5)
        raise RuntimeError("o Metabase não respondeu em /api/health")

    def entrar(self, email: str, senha: str) -> None:
        propriedades = self._pedir("GET", "/api/session/properties")
        if not propriedades.get("has-user-setup"):
            logger.info("primeira subida: fazendo a configuração inicial com %s", email)
            sessao = self._pedir(
                "POST",
                "/api/setup",
                json={
                    "token": propriedades["setup-token"],
                    "user": {
                        "email": email,
                        "password": senha,
                        "first_name": "InflaTrack",
                        "last_name": "Squad",
                        "site_name": "InflaTrack",
                    },  # fmt: skip
                    "prefs": {"site_name": "InflaTrack", "allow_tracking": False},
                },
            )
        else:
            sessao = self._pedir(
                "POST", "/api/session", json={"username": email, "password": senha}
            )
        self.cliente.headers["X-Metabase-Session"] = sessao["id"]

    def garantir_banco(self, banco: dict[str, Any]) -> int:
        """Reaproveita a conexão com o mesmo nome ou que aponte para o mesmo lugar (uma
        conexão criada à mão na interface, com outro nome, não vira duplicata)."""
        resposta = self._pedir("GET", "/api/database")
        existentes = resposta["data"] if isinstance(resposta, dict) else resposta
        for existente in existentes:
            if existente["name"] == banco["nome"] or mesmo_destino(existente, banco):
                return existente["id"]
        logger.info("criando a conexão %s", banco["nome"])
        criado = self._pedir(
            "POST",
            "/api/database",
            json={
                "name": banco["nome"],
                "engine": banco["engine"],
                "details": detalhes_do_banco(banco),
            },  # fmt: skip
        )
        return criado["id"]

    def garantir_colecao(self, nome: str) -> int:
        for colecao in self._pedir("GET", "/api/collection"):
            if colecao.get("name") == nome and not colecao.get("archived"):
                return colecao["id"]
        return self._pedir("POST", "/api/collection", json={"name": nome})["id"]

    def itens_da_colecao(self, id_colecao: int, modelo: str) -> dict[str, int]:
        itens = self._pedir("GET", f"/api/collection/{id_colecao}/items", params={"models": modelo})
        itens = itens["data"] if isinstance(itens, dict) else itens
        return {item["name"]: item["id"] for item in itens}

    def garantir_pergunta(self, corpo: dict[str, Any], existentes: dict[str, int]) -> int:
        if corpo["name"] in existentes:
            id_card = existentes[corpo["name"]]
            self._pedir("PUT", f"/api/card/{id_card}", json=corpo)
            return id_card
        return self._pedir("POST", "/api/card", json=corpo)["id"]

    def garantir_dashboard(
        self, painel: Painel, id_colecao: int, cards: list[tuple[int, Pergunta]]
    ) -> int:
        existentes = self.itens_da_colecao(id_colecao, "dashboard")
        if painel.nome in existentes:
            id_dash = existentes[painel.nome]
        else:
            id_dash = self._pedir(
                "POST",
                "/api/dashboard",
                json={
                    "name": painel.nome,
                    "description": painel.descricao,
                    "collection_id": id_colecao,
                },  # fmt: skip
            )["id"]
        atuais = self._pedir("GET", f"/api/dashboard/{id_dash}").get("dashcards", [])
        id_por_card = {d["card_id"]: d["id"] for d in atuais if d.get("card_id")}
        dashcards = [
            {
                "id": id_por_card.get(id_card, -(i + 1)),  # negativo = cartão novo
                "card_id": id_card,
                "row": p.linha,
                "col": p.coluna,
                "size_x": p.largura,
                "size_y": p.altura,
                "parameter_mappings": [],
                "visualization_settings": {},
            }  # fmt: skip
            for i, (id_card, p) in enumerate(cards)
        ]
        self._pedir(
            "PUT",
            f"/api/dashboard/{id_dash}",
            json={"description": painel.descricao, "dashcards": dashcards},
        )
        return id_dash


def sincronizar(metabase: Metabase, painel: Painel) -> int:
    usados = {pergunta.banco for pergunta in painel.perguntas}
    ids_bancos = {chave: metabase.garantir_banco(painel.bancos[chave]) for chave in sorted(usados)}
    id_colecao = metabase.garantir_colecao(painel.colecao)
    existentes = metabase.itens_da_colecao(id_colecao, "card")
    cards = []
    for pergunta in painel.perguntas:
        corpo = corpo_da_pergunta(pergunta, ids_bancos[pergunta.banco], id_colecao)
        cards.append((metabase.garantir_pergunta(corpo, existentes), pergunta))
        logger.info("pergunta ok: %s", pergunta.titulo)
    id_dash = metabase.garantir_dashboard(painel, id_colecao, cards)
    logger.info("dashboard ok: %s (id %d, %d perguntas)", painel.nome, id_dash, len(cards))
    return id_dash


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    porta = os.environ.get("METABASE_PORT", "3001")
    parser.add_argument(
        "--url", default=os.environ.get("METABASE_URL", f"http://localhost:{porta}")
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    email, senha = os.environ.get("METABASE_EMAIL"), os.environ.get("METABASE_SENHA")
    if not email or not senha:
        logger.error("defina METABASE_EMAIL e METABASE_SENHA no .env (ver .env.example)")
        return 1

    metabase = Metabase(args.url)
    try:
        metabase.esperar_subir()
        metabase.entrar(email, senha)
        id_dash = sincronizar(metabase, ler_painel())
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError) as erro:
        logger.error("sincronização interrompida: %s", erro)
        return 1
    logger.info("abra %s/dashboard/%d", args.url, id_dash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
