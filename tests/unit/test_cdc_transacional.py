"""CDC, Nível 1: decodificação do pgoutput e remoção do CNPJ, sem banco.

As mensagens são montadas byte a byte conforme a documentação do protocolo de replicação lógica
do Postgres 16 ("Logical Replication Message Formats"). O teste de integração confere o mesmo
decodificador contra um Postgres de verdade.
"""

import json
import struct
from datetime import UTC, datetime

import pytest

from inflatrack.cdc import transacional

CHAVE = "chave-de-teste"
CNPJ = "11222333000181"


def _texto(valor: str) -> bytes:
    return valor.encode("utf-8") + b"\0"


def _tupla(*valores: str | None) -> bytes:
    corpo = struct.pack(">h", len(valores))
    for valor in valores:
        if valor is None:
            corpo += b"n"
        elif valor == "<toast>":
            corpo += b"u"
        else:
            bruto = valor.encode("utf-8")
            corpo += b"t" + struct.pack(">i", len(bruto)) + bruto
    return corpo


def _relacao(relid: int, tabela: str, colunas: list[str], schema: str = "public") -> bytes:
    corpo = b"R" + struct.pack(">i", relid) + _texto(schema) + _texto(tabela) + b"f"
    corpo += struct.pack(">h", len(colunas))
    for coluna in colunas:
        corpo += b"\0" + _texto(coluna) + struct.pack(">ii", 25, -1)
    return corpo


def _inicio(lsn: int = 500, xid: int = 7) -> bytes:
    # 1 segundo depois de 2000-01-01, a época do Postgres.
    return b"B" + struct.pack(">qqI", lsn, 1_000_000, xid)


def _fim(fim: int = 600) -> bytes:
    return b"C\0" + struct.pack(">qqq", 500, fim, 1_000_000)


def _mensagens(*corpos: bytes) -> list[tuple[int, int, bytes]]:
    return [(100 + i, 7, corpo) for i, corpo in enumerate(corpos)]


COLUNAS = ["id", "nome"]
RELACAO = _relacao(1, "produto", COLUNAS)


def test_insert_vira_mudanca_com_a_transacao_e_a_hora_do_commit() -> None:
    insert = b"I" + struct.pack(">i", 1) + b"N" + _tupla("9", "Arroz")

    (mudanca,), fim = transacional.decodificar(_mensagens(_inicio(), RELACAO, insert, _fim()))

    assert fim == 600
    assert mudanca["operacao"] == "I"
    assert mudanca["tabela"] == "produto"
    assert (mudanca["lsn_commit"], mudanca["id_transacao"]) == (500, 7)
    assert mudanca["depois"] == {"id": "9", "nome": "Arroz"}
    assert mudanca["antes"] is None
    assert mudanca["commit_em"] == datetime(2000, 1, 1, 0, 0, 1, tzinfo=UTC)


def test_update_com_replica_identity_full_traz_a_linha_anterior() -> None:
    update = (
        b"U" + struct.pack(">i", 1) + b"O" + _tupla("9", "Arroz") + b"N" + _tupla("9", "Arroz 5kg")
    )

    (mudanca,), _ = transacional.decodificar(_mensagens(_inicio(), RELACAO, update, _fim()))

    assert mudanca["antes"] == {"id": "9", "nome": "Arroz"}
    assert mudanca["depois"] == {"id": "9", "nome": "Arroz 5kg"}


def test_update_preenche_coluna_toast_nao_reenviada_com_o_valor_anterior() -> None:
    update = (
        b"U" + struct.pack(">i", 1) + b"O" + _tupla("9", "Longo") + b"N" + _tupla("10", "<toast>")
    )

    (mudanca,), _ = transacional.decodificar(_mensagens(_inicio(), RELACAO, update, _fim()))

    assert mudanca["depois"] == {"id": "10", "nome": "Longo"}


def test_delete_guarda_a_linha_apagada_em_antes() -> None:
    delete = b"D" + struct.pack(">i", 1) + b"O" + _tupla("9", None)

    (mudanca,), _ = transacional.decodificar(_mensagens(_inicio(), RELACAO, delete, _fim()))

    assert (mudanca["operacao"], mudanca["depois"]) == ("D", None)
    assert mudanca["antes"] == {"id": "9", "nome": None}


def test_truncate_e_registrado_sem_linha() -> None:
    truncate = b"T" + struct.pack(">i", 1) + b"\0" + struct.pack(">i", 1)

    (mudanca,), _ = transacional.decodificar(_mensagens(_inicio(), RELACAO, truncate, _fim()))

    assert mudanca["operacao"] == "T"


def test_relacao_fora_de_public_e_recusada() -> None:
    """O CDC lê só `public`: o que o pipeline grava em `serie` não pode voltar para a Bronze."""
    with pytest.raises(transacional.CdcError, match=r"serie\.fato"):
        transacional.decodificar(_mensagens(_inicio(), _relacao(2, "fato", COLUNAS, "serie")))


def test_lote_sem_commit_nao_informa_posicao_para_avancar() -> None:
    _, fim = transacional.decodificar(_mensagens(_inicio(), RELACAO))

    assert fim is None


def _mudanca_lojista(antes=None, depois=None, operacao="I") -> dict:
    return {
        "lsn": 1,
        "lsn_commit": 1,
        "id_transacao": 1,
        "tabela": "lojista",
        "operacao": operacao,
        "antes": antes,
        "depois": depois,
        "commit_em": datetime(2026, 1, 1, tzinfo=UTC),
    }


LOJISTA = {
    "id": "3",
    "nome_fantasia": "João Silva MEI",
    "cnpj": CNPJ,
    "codigo_localidade": "5300108",
    "codigo_grupo_ipca": "1",
    "criado_em": "2026-01-01 00:00:00+00",
}


def test_lojista_perde_cnpj_e_nome_e_ganha_o_hash_tambem_na_linha_anterior() -> None:
    linha = transacional._para_linha(_mudanca_lojista(LOJISTA, LOJISTA, "U"), CHAVE)

    assert CNPJ not in str(linha)
    assert "João" not in str(linha)
    for lado in (json.loads(linha["antes"]), json.loads(linha["depois"])):
        assert lado["hash_estabelecimento"] == transacional.hash_estabelecimento(CNPJ, CHAVE)
        assert set(lado) == {*transacional.COLUNAS_LOJISTA, "hash_estabelecimento"}


def test_coluna_nova_em_lojista_nao_passa_por_esquecimento() -> None:
    linha = transacional._para_linha(
        _mudanca_lojista(depois=LOJISTA | {"email": "pessoa@exemplo.com"}), CHAVE
    )

    assert "pessoa@exemplo.com" not in str(linha)


def test_o_hash_depende_da_chave_e_nao_contem_o_cnpj() -> None:
    primeiro = transacional.hash_estabelecimento(CNPJ, CHAVE)

    assert primeiro == transacional.hash_estabelecimento(CNPJ, CHAVE)
    assert primeiro != transacional.hash_estabelecimento(CNPJ, "outra-chave")
    assert CNPJ not in primeiro


def test_captura_sem_chave_recusa_antes_de_tocar_no_banco(tmp_path) -> None:
    with pytest.raises(transacional.CdcError, match="CDC_CHAVE_PSEUDONIMO"):
        transacional.capturar(None, tmp_path, "")
