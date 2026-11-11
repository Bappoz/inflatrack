"""Gerador de CSV e de pacote anual no formato do BDMEP (INMET) para os testes de clima.

O cabeçalho é o de um arquivo real (``tests/fixtures/clima/bdmep_A001_2025.csv``); só as linhas
horárias são sintéticas, para que o teste saiba de antemão a média, a chuva e a anomalia.
"""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

from inflatrack.clients.inmet import VersaoZip, url_zip_anual

FIXTURES = Path(__file__).parent / "fixtures" / "clima"
CSV_2025 = FIXTURES / "bdmep_A001_2025.csv"
CSV_2006 = FIXTURES / "bdmep_A001_2006.csv"
# Em 2019 os acentos do cabeçalho de metadados vieram como "?" ("DATA DE FUNDAC?O").
CSV_2019 = FIXTURES / "bdmep_A001_2019.csv"


def _decimal(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def csv_bdmep(estacao_id: str, dias: dict[date, tuple[float, float]], horas: int = 24) -> str:
    """CSV de uma estação: em cada dia, ``horas`` leituras com temperatura e chuva horária fixas.

    Máxima e mínima da hora ficam 0,5 °C acima e abaixo; umidade 70% (mínima 65%).
    """
    cabecalho = CSV_2025.read_text(encoding="latin-1").splitlines()[:9]
    cabecalho[3] = f"CODIGO (WMO):;{estacao_id}"
    linhas = list(cabecalho)
    for dia, (temperatura, chuva_hora) in sorted(dias.items()):
        for hora in range(horas):
            campos = [""] * 19
            campos[0] = f"{dia:%Y/%m/%d}"
            campos[1] = f"{hora:02d}00 UTC"
            campos[2] = _decimal(chuva_hora)
            campos[7] = _decimal(temperatura)
            campos[9] = _decimal(temperatura + 0.5)
            campos[10] = _decimal(temperatura - 0.5)
            campos[14] = "65"
            campos[15] = "70"
            linhas.append(";".join(campos) + ";")
    return "\n".join(linhas) + "\n"


def nome_no_pacote(ano: int, estacao_id: str) -> str:
    return f"{ano}/INMET_CO_DF_{estacao_id}_TESTE_01-01-{ano}_A_31-12-{ano}.CSV"


def gravar_pacote(caminho: Path, ano: int, csvs: dict[str, str]) -> Path:
    """Pacote anual com um CSV (latin-1) por estação, como o portal publica."""
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as pacote:
        for estacao_id, texto in csvs.items():
            pacote.writestr(nome_no_pacote(ano, estacao_id), texto.encode("latin-1"))
    return caminho


class ClienteBdmepFalso:
    """Faz o papel do portal: um pacote por ano, com versão controlada pelo teste."""

    def __init__(self, pacotes: dict[int, dict[str, str]], versao: str = "v1") -> None:
        self.pacotes = pacotes
        self.versao = versao
        self.baixados: list[int] = []
        self.falhar_em: set[int] = set()

    def versao_zip_anual(self, ano: int) -> VersaoZip | None:
        if ano not in self.pacotes:
            return None
        return VersaoZip(ano, url_zip_anual(ano), f"{self.versao}-{ano}", 1000 + ano)

    def baixar_zip_anual(self, ano: int, destino: Path) -> Path:
        self.baixados.append(ano)
        if ano in self.falhar_em:
            raise OSError(f"queda de rede simulada em {ano}")
        return gravar_pacote(destino, ano, self.pacotes[ano])
