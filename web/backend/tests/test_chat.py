"""Felicia falando direto com o proxy LiteLLM (formato OpenAI), com o httpx simulado."""

import asyncio
import json

import httpx
import pytest

from web.backend import chat


@pytest.fixture(autouse=True)
def proxy_configurado(monkeypatch):
    monkeypatch.setenv("LITELLM_PROXY_URL", "https://proxy.example/")
    monkeypatch.setenv("LITELLM_API_KEY", "chave-teste")
    monkeypatch.delenv("LITELLM_MODEL", raising=False)
    monkeypatch.setattr(chat, "ESPERA_PARTIDA_A_FRIO", 0)


def _resposta_texto(texto: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": texto}}]}


def _resposta_ferramenta(*chamadas: tuple[str, str, dict]) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": id_,
                            "type": "function",
                            "function": {"name": nome, "arguments": json.dumps(args)},
                        }
                        for id_, nome, args in chamadas
                    ],
                }
            }
        ]
    }


class ProxyFalso:
    """Devolve as respostas em ordem e guarda o corpo de cada requisição."""

    def __init__(self, *respostas) -> None:
        self.respostas = list(respostas)
        self.requisicoes: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, httpx.Response):
            return resposta
        if isinstance(resposta, Exception):
            raise resposta
        return httpx.Response(200, json=resposta)

    def corpo(self, indice: int) -> dict:
        return json.loads(self.requisicoes[indice].content)


def _responder(proxy: ProxyFalso, texto="Oi", historico=None, ferramentas=None) -> str:
    return asyncio.run(
        chat.responder(
            texto,
            historico or [],
            ferramentas or {},
            transport=httpx.MockTransport(proxy),
        )
    )


def test_resposta_direta_envia_instrucao_historico_e_pergunta() -> None:
    proxy = ProxyFalso(_resposta_texto("Olá!"))
    historico = [
        {"role": "user", "text": "Qual o IPCA?"},
        {"role": "assistant", "text": "4,5% em 12 meses."},
    ]

    resposta = _responder(proxy, "E o INPC?", historico)

    assert resposta == "Olá!"
    requisicao = proxy.requisicoes[0]
    assert str(requisicao.url) == "https://proxy.example/v1/chat/completions"
    assert requisicao.headers["Authorization"] == "Bearer chave-teste"
    corpo = proxy.corpo(0)
    assert corpo["model"] == "gpt-5.4-mini"
    assert corpo["messages"] == [
        {"role": "system", "content": chat.INSTRUCAO},
        {"role": "user", "content": "Qual o IPCA?"},
        {"role": "assistant", "content": "4,5% em 12 meses."},
        {"role": "user", "content": "E o INPC?"},
    ]
    nomes = {f["function"]["name"] for f in corpo["tools"]}
    assert nomes == {"consultar_inflacao", "buscar_produto", "prever_reajuste"}


def test_modelo_vem_da_variavel_de_ambiente(monkeypatch) -> None:
    monkeypatch.setenv("LITELLM_MODEL", "outro-modelo")
    proxy = ProxyFalso(_resposta_texto("ok"))

    _responder(proxy)

    assert proxy.corpo(0)["model"] == "outro-modelo"


def test_executa_uma_ferramenta_e_devolve_o_resultado_ao_modelo() -> None:
    chamadas = []

    def buscar_produto(nome: str) -> dict:
        chamadas.append(nome)
        return {"produtos": [{"codigo_subitem": "1101002", "nome": "Arroz"}]}

    proxy = ProxyFalso(
        _resposta_ferramenta(("call_1", "buscar_produto", {"nome": "arroz"})),
        _resposta_texto("Achei o arroz."),
    )

    resposta = _responder(proxy, "arroz", ferramentas={"buscar_produto": buscar_produto})

    assert resposta == "Achei o arroz."
    assert chamadas == ["arroz"]
    mensagens = proxy.corpo(1)["messages"]
    assert mensagens[-2]["role"] == "assistant"
    assert mensagens[-2]["tool_calls"][0]["id"] == "call_1"
    assert mensagens[-1]["role"] == "tool"
    assert mensagens[-1]["tool_call_id"] == "call_1"
    assert json.loads(mensagens[-1]["content"]) == {
        "produtos": [{"codigo_subitem": "1101002", "nome": "Arroz"}]
    }


def test_varias_rodadas_e_varias_ferramentas_na_mesma_rodada() -> None:
    def buscar_produto(nome: str) -> dict:
        return {"produtos": [{"codigo_subitem": "1", "nome": nome}]}

    def prever_reajuste(codigo_subitem: str, uf: str, preco_atual: float) -> dict:
        return {"preco_sugerido": preco_atual * 1.01, "uf": uf}

    def consultar_inflacao() -> dict:
        return {"kpis": {"ipca_12m": 4.5}}

    proxy = ProxyFalso(
        _resposta_ferramenta(
            ("a", "buscar_produto", {"nome": "arroz"}),
            ("b", "consultar_inflacao", {}),
        ),
        _resposta_ferramenta(
            ("c", "prever_reajuste", {"codigo_subitem": "1", "uf": "SP", "preco_atual": 10.0})
        ),
        _resposta_texto("Sugiro R$ 10,10."),
    )

    resposta = _responder(
        proxy,
        ferramentas={
            "buscar_produto": buscar_produto,
            "prever_reajuste": prever_reajuste,
            "consultar_inflacao": consultar_inflacao,
        },
    )

    assert resposta == "Sugiro R$ 10,10."
    assert len(proxy.requisicoes) == 3
    ultima = proxy.corpo(2)["messages"]
    resultados = [m for m in ultima if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in resultados] == ["a", "b", "c"]
    assert json.loads(resultados[2]["content"]) == {"preco_sugerido": 10.1, "uf": "SP"}


def test_argumentos_estranhos_viram_erro_para_o_modelo_sem_derrubar_a_conversa() -> None:
    def consultar_inflacao() -> dict:
        return {"kpis": {}}

    proxy = ProxyFalso(
        # o modelo inventou um argumento e chamou uma ferramenta que não existe
        _resposta_ferramenta(
            ("a", "consultar_inflacao", {"praca": "Brasil"}),
            ("b", "apagar_banco", {}),
        ),
        _resposta_texto("Pronto."),
    )

    resposta = _responder(proxy, ferramentas={"consultar_inflacao": consultar_inflacao})

    assert resposta == "Pronto."
    resultados = [m for m in proxy.corpo(1)["messages"] if m["role"] == "tool"]
    assert json.loads(resultados[0]["content"]) == {"kpis": {}}
    assert "erro" in json.loads(resultados[1]["content"])


def test_falha_dentro_da_ferramenta_vira_erro_para_o_modelo() -> None:
    def consultar_inflacao() -> dict:
        raise RuntimeError("banco fora do ar")

    proxy = ProxyFalso(
        _resposta_ferramenta(("a", "consultar_inflacao", {})),
        _resposta_texto("Não consegui ler os dados."),
    )

    resposta = _responder(proxy, ferramentas={"consultar_inflacao": consultar_inflacao})

    assert resposta == "Não consegui ler os dados."
    resultado = [m for m in proxy.corpo(1)["messages"] if m["role"] == "tool"][0]
    assert "erro" in json.loads(resultado["content"])
    assert "banco fora do ar" not in resultado["content"]


def test_para_depois_do_limite_de_rodadas() -> None:
    def consultar_inflacao() -> dict:
        return {}

    proxy = ProxyFalso(
        *[_resposta_ferramenta((f"c{i}", "consultar_inflacao", {})) for i in range(10)]
    )

    resposta = _responder(proxy, ferramentas={"consultar_inflacao": consultar_inflacao})

    assert len(proxy.requisicoes) == chat.MAX_RODADAS
    assert resposta  # mensagem amigável, não vazia
    assert "consultar_inflacao" not in resposta


@pytest.mark.parametrize(
    "falha",
    [
        [httpx.Response(503, text="App port is not ready")] * 2,
        httpx.Response(403, json={"error": "modelo não permitido"}),
        httpx.Response(200, json={"sem": "choices"}),
        httpx.ConnectError("sem rede"),
        httpx.ReadTimeout("demorou"),
    ],
)
def test_erro_do_proxy_vira_felicia_indisponivel(falha) -> None:
    proxy = ProxyFalso(*(falha if isinstance(falha, list) else [falha]))

    with pytest.raises(chat.FeliciaIndisponivel):
        _responder(proxy)


def test_chat_configurado_exige_url_e_chave(monkeypatch) -> None:
    assert chat.chat_configurado()
    monkeypatch.delenv("LITELLM_API_KEY")
    assert not chat.chat_configurado()


def test_tenta_de_novo_uma_vez_quando_o_proxy_esta_acordando() -> None:
    proxy = ProxyFalso(httpx.Response(503, text="App port is not ready"), _resposta_texto("Oi!"))

    assert _responder(proxy) == "Oi!"
    assert len(proxy.requisicoes) == 2
