"""Felicia, a assistente do site: fala com o modelo direto no proxy LiteLLM (formato OpenAI).

O servidor não guarda a conversa. O navegador manda as últimas mensagens em cada pergunta, e
este módulo faz o laço de ferramentas: pergunta ao modelo, executa as `tool_calls` que ele pedir,
devolve os resultados com `role: "tool"` e repete até vir um texto (no máximo MAX_RODADAS).
"""

import asyncio
import inspect
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence

import httpx
from starlette.concurrency import run_in_threadpool

Ferramenta = Callable[..., dict]

logger = logging.getLogger(__name__)

MODELO_PADRAO = "gpt-5.4-mini"
MAX_RODADAS = 5
# O proxy pode ter partida a frio (já respondeu 503 "App port is not ready").
TIMEOUT = httpx.Timeout(45.0, connect=10.0)
ESPERA_PARTIDA_A_FRIO = 3.0  # segundos antes da única nova tentativa depois de um 503
MENSAGEM_LIMITE = (
    "Não consegui concluir a consulta agora. Tente perguntar de outro jeito, "
    "com menos coisas de uma vez."
)

INSTRUCAO = """Você é a Felicia, assistente do InflaTrack, um painel de inflação brasileira.
Responda em português, de forma curta e clara. Use só o que as ferramentas retornarem; se elas
não trouxerem o dado pedido, diga isso em vez de inventar.
- Números de inflação (IPCA, INPC, setores, praças): chame `consultar_inflacao`.
- Quanto reajustar o preço de um produto: chame `buscar_produto` com o nome, confirme o produto
  se houver mais de uma opção, peça a UF e o preço atual se faltarem, e chame `prever_reajuste`.
  Responda com o preço sugerido e o mês previsto, e diga que é uma estimativa. Se `confianca`
  for "alta", cite a faixa; se for "baixa", não cite a faixa e avise que o item varia muito de
  um mês para o outro, sugerindo acompanhar o preço do fornecedor.
- Se `buscar_produto` não achar o nome (marca ou nome popular), tente o nome genérico da
  categoria do IPCA, como Coca-Cola → refrigerante e pãozinho → pão francês, antes de dizer
  que não há o produto.
Fora desse assunto, diga que só ajuda com os dados do InflaTrack."""

# O ADK deduzia estes esquemas das funções Python; sem ele, ficam escritos à mão.
ESQUEMAS_FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_inflacao",
            "description": (
                "IPCA/INPC em 12 meses, inflação por setor e por praça, do último mês "
                "divulgado (Brasil). Não recebe argumentos."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_produto",
            "description": (
                'Procura produtos (subitens do IPCA) pelo nome, como "arroz" ou "gasolina". '
                "Devolve até 10 opções com o `codigo_subitem`, que `prever_reajuste` precisa."
            ),
            "parameters": {
                "type": "object",
                "properties": {"nome": {"type": "string", "description": "Nome do produto."}},
                "required": ["nome"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prever_reajuste",
            "description": (
                "Sugere o preço do produto para o próximo mês, pela inflação prevista na "
                "praça da UF."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_subitem": {
                        "type": "string",
                        "description": "Código do produto, vindo de `buscar_produto`.",
                    },
                    "uf": {
                        "type": "string",
                        "description": 'Sigla do estado do lojista, como "SP".',
                    },
                    "preco_atual": {
                        "type": "number",
                        "description": "Preço que o lojista cobra hoje, em reais.",
                    },
                },
                "required": ["codigo_subitem", "uf", "preco_atual"],
                "additionalProperties": False,
            },
        },
    },
]


class FeliciaIndisponivel(Exception):
    """O proxy não respondeu, respondeu com erro ou mandou algo fora do formato esperado."""


def chat_configurado() -> bool:
    return bool(os.getenv("LITELLM_PROXY_URL") and os.getenv("LITELLM_API_KEY"))


def _mensagens_iniciais(texto: str, historico: Sequence[Mapping[str, str]]) -> list[dict]:
    mensagens: list[dict] = [{"role": "system", "content": INSTRUCAO}]
    mensagens += [{"role": item["role"], "content": item["text"]} for item in historico]
    mensagens.append({"role": "user", "content": texto})
    return mensagens


async def _executar(nome: str, argumentos: str, ferramentas: Mapping[str, Ferramenta]) -> dict:
    funcao = ferramentas.get(nome)
    if funcao is None:
        return {"erro": f"A ferramenta {nome} não existe."}
    try:
        args = json.loads(argumentos or "{}")
    except json.JSONDecodeError:
        return {"erro": "Argumentos inválidos."}
    if not isinstance(args, dict):
        return {"erro": "Argumentos inválidos."}
    # O modelo às vezes inventa argumentos (já pediu consultar_inflacao(praca="Brasil")).
    aceitos = inspect.signature(funcao).parameters
    args = {chave: valor for chave, valor in args.items() if chave in aceitos}
    try:
        return await run_in_threadpool(funcao, **args)
    except TypeError:
        return {"erro": "Argumentos inválidos."}
    except Exception:
        logger.exception("Ferramenta %s falhou", nome)
        return {"erro": "Não foi possível consultar os dados agora."}


async def _post(client: httpx.AsyncClient, mensagens: list[dict]) -> httpx.Response:
    try:
        return await client.post(
            "/v1/chat/completions",
            json={
                "model": os.getenv("LITELLM_MODEL", MODELO_PADRAO),
                "messages": mensagens,
                "tools": ESQUEMAS_FERRAMENTAS,
            },
        )
    except httpx.HTTPError as error:
        raise FeliciaIndisponivel(f"Falha ao falar com o proxy: {type(error).__name__}") from error


async def _perguntar(client: httpx.AsyncClient, mensagens: list[dict]) -> dict:
    resposta = await _post(client, mensagens)
    if resposta.status_code == 503:
        # Partida a frio do proxy ("App port is not ready"): espera um pouco e tenta só mais uma.
        await asyncio.sleep(ESPERA_PARTIDA_A_FRIO)
        resposta = await _post(client, mensagens)
    if resposta.is_error:
        raise FeliciaIndisponivel(f"O proxy respondeu HTTP {resposta.status_code}")
    try:
        mensagem = resposta.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise FeliciaIndisponivel("Resposta do proxy fora do formato esperado") from error
    if not isinstance(mensagem, dict):
        raise FeliciaIndisponivel("Resposta do proxy fora do formato esperado")
    return mensagem


async def responder(
    texto: str,
    historico: Sequence[Mapping[str, str]],
    ferramentas: Mapping[str, Ferramenta],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Responde `texto` levando em conta o `historico` ({role, text}) mandado pelo navegador."""
    mensagens = _mensagens_iniciais(texto, historico)
    async with httpx.AsyncClient(
        base_url=os.environ["LITELLM_PROXY_URL"].rstrip("/"),
        headers={"Authorization": f"Bearer {os.environ['LITELLM_API_KEY']}"},
        timeout=TIMEOUT,
        transport=transport,
    ) as client:
        for _ in range(MAX_RODADAS):
            mensagem = await _perguntar(client, mensagens)
            chamadas = mensagem.get("tool_calls") or []
            if not chamadas:
                return mensagem.get("content") or ""
            mensagens.append(
                {"role": "assistant", "content": mensagem.get("content"), "tool_calls": chamadas}
            )
            for chamada in chamadas:
                funcao = chamada.get("function") or {}
                resultado = await _executar(
                    funcao.get("name", ""), funcao.get("arguments", ""), ferramentas
                )
                mensagens.append(
                    {
                        "role": "tool",
                        "tool_call_id": chamada.get("id"),
                        "content": json.dumps(resultado, ensure_ascii=False, default=str),
                    }
                )
    return MENSAGEM_LIMITE
