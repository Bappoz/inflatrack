"""Felicia, a assistente do site: agente Google ADK que fala com o modelo via proxy LiteLLM."""

import os
from collections.abc import Callable

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

Ferramenta = Callable[..., dict]

APP_NAME = "inflatrack-felicia"

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


def _criar_modelo() -> LiteLlm:
    return LiteLlm(
        model=os.getenv("LITELLM_MODEL", "openai/gpt-4o-mini"),
        api_base=os.environ["LITELLM_PROXY_URL"],
        api_key=os.environ["LITELLM_API_KEY"],
    )


_sessoes = InMemorySessionService()
_runner: Runner | None = None


def chat_configurado() -> bool:
    return bool(os.getenv("LITELLM_PROXY_URL") and os.getenv("LITELLM_API_KEY"))


def _runner_unico(ferramentas: list[Ferramenta]) -> Runner:
    global _runner
    if _runner is None:
        agente = Agent(
            name="felicia",
            model=_criar_modelo(),
            instruction=INSTRUCAO,
            tools=list(ferramentas),
        )
        _runner = Runner(app_name=APP_NAME, agent=agente, session_service=_sessoes)
    return _runner


async def responder(
    user_id: str, session_id: str, texto: str, ferramentas: list[Ferramenta]
) -> str:
    """Uma conversa por (usuário, sessão); o histórico fica em memória do processo."""
    runner = _runner_unico(ferramentas)
    if not await _sessoes.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id):
        await _sessoes.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
    resposta = ""
    async for evento in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=mensagem
    ):
        if evento.is_final_response() and evento.content and evento.content.parts:
            resposta = "".join(p.text or "" for p in evento.content.parts)
    return resposta
