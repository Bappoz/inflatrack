"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { DashboardData } from "./tipos";
import { ChartPanel, apiUrl, getComCache, monthLong, percentage, reais } from "./formato";

const UFS = [
  "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
  "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
];

type Produto = { codigo_subitem: string; nome: string; nome_grupo: string };
type Destaque = Produto & { variacao_prevista_pct: number };
type Reajuste = {
  produto: string;
  praca: string;
  mes_previsto: string;
  variacao_prevista_pct: number;
  preco_sugerido: number;
  faixa_preco: [number, number];
  ipca_12m_pct: number | null;
  confianca: "alta" | "baixa";
};

/** "subiu 2,10%", "caiu 0,18%" ou "ficou estável", conforme o sinal. */
function variacao(pct: number, subiu: string, caiu: string, estavel: string): string {
  if (Math.abs(pct) < 0.005) return estavel;
  return `${pct > 0 ? subiu : caiu} ${percentage(Math.abs(pct))}`;
}

/** Minúsculas e sem acento: "Pão" e "pao" se encontram. */
function semAcento(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Até 10 produtos cujo nome contém o termo; os que começam com ele vêm primeiro. */
function filtrar(catalogo: Produto[], busca: string): Produto[] {
  const termo = semAcento(busca.trim());
  if (termo.length < 2) return [];
  return catalogo
    .map((item) => ({ item, posicao: semAcento(item.nome).indexOf(termo) }))
    .filter(({ posicao }) => posicao >= 0)
    .sort((a, b) => a.posicao - b.posicao || a.item.nome.length - b.item.nome.length)
    .slice(0, 10)
    .map(({ item }) => item);
}

/** "12,50", "R$ 1.234,56", "1.234" ou "12.5" viram número; texto inválido vira NaN. */
function lerPreco(texto: string): number {
  const limpo = texto.replace(/[R$\s]/g, "");
  // "1.234" é mil duzentos e trinta e quatro (milhar), não 1,234.
  const soMilhar = /^\d{1,3}(\.\d{3})+$/.test(limpo);
  const normalizado =
    limpo.includes(",") || soMilhar ? limpo.replace(/\./g, "").replace(",", ".") : limpo;
  return normalizado ? Number(normalizado) : Number.NaN;
}

export default function Produtos({
  pracas,
  ufConta,
}: {
  pracas: DashboardData["location_options"];
  ufConta: string | null;
}) {
  const router = useRouter();
  const [busca, setBusca] = useState("");
  const [catalogo, setCatalogo] = useState<Produto[]>([]);
  const [produto, setProduto] = useState<Produto | null>(null);
  const [preco, setPreco] = useState("");
  const [uf, setUf] = useState(ufConta && UFS.includes(ufConta) ? ufConta : "SP");
  // A praça do IPCA da UF escolhida; UF sem praça no IPCA usa o Brasil (mesma regra do backend).
  const praca = pracas.find((item) => item.uf?.toUpperCase() === uf);
  const codigoLocalidade = praca?.codigo_localidade ?? 1;
  const nomePraca = praca?.nome_localidade ?? "Brasil";
  const [resultado, setResultado] = useState<Reajuste | null>(null);
  const [erro, setErro] = useState("");
  const [calculando, setCalculando] = useState(false);
  // Guarda de qual praça é a lista: trocar de praça mostra "Carregando…" sem zerar o estado.
  const [destaquesDe, setDestaquesDe] = useState<{ praca: number; itens: Destaque[] } | null>(
    null,
  );
  const destaques = destaquesDe?.praca === codigoLocalidade ? destaquesDe.itens : null;
  const sugestoes = useMemo(() => filtrar(catalogo, busca), [catalogo, busca]);
  const sugestoesVisiveis = produto ? [] : sugestoes;

  useEffect(() => {
    // A lista inteira (~380 nomes) vem uma vez e fica 24 h no cache: a busca é local e instantânea.
    let ativo = true;
    getComCache(`${apiUrl}/produtos`)
      .then(({ status, ok, corpo }) => {
        if (status === 401) return router.replace("/login");
        if (ativo && ok) setCatalogo((corpo as { produtos: Produto[] }).produtos);
      })
      .catch(() => null);
    return () => {
      ativo = false;
    };
  }, [router]);

  useEffect(() => {
    let ativo = true;
    getComCache(`${apiUrl}/previsoes/destaques?localidade=${codigoLocalidade}`)
      .then(({ status, ok, corpo }) => {
        if (status === 401) return router.replace("/login");
        const itens = ok ? (corpo as { destaques: Destaque[] }).destaques : [];
        if (ativo) setDestaquesDe({ praca: codigoLocalidade, itens });
      })
      .catch(() => ativo && setDestaquesDe({ praca: codigoLocalidade, itens: [] }));
    return () => {
      ativo = false;
    };
  }, [codigoLocalidade, router]);

  async function calcular(event: React.FormEvent) {
    event.preventDefault();
    setErro("");
    setResultado(null);
    const valor = lerPreco(preco);
    if (!produto) return setErro("Escolha um produto da lista de sugestões.");
    if (!Number.isFinite(valor) || valor <= 0) return setErro("Informe o preço atual, como 12,50.");
    setCalculando(true);
    try {
      const resposta = await fetch(`${apiUrl}/reajuste`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codigo_subitem: produto.codigo_subitem, uf, preco_atual: valor }),
      });
      if (resposta.status === 401) return router.replace("/login");
      const corpo = await resposta.json().catch(() => null);
      if (resposta.ok) setResultado(corpo as Reajuste);
      else setErro(typeof corpo?.detail === "string" ? corpo.detail : "Não foi possível calcular.");
    } catch {
      setErro("Não consegui falar com o servidor. Tente de novo em instantes.");
    } finally {
      setCalculando(false);
    }
  }

  return (
    <div className="dashboard-grid">
      <ChartPanel
        title="Quanto cobrar no mês que vem"
        subtitle="Digite um produto e o preço que você cobra hoje. A sugestão usa a inflação prevista para a sua região."
      >
        <form className="simulador" onSubmit={calcular}>
          <label className="simulador-produto">
            <span>Produto</span>
            <input
              value={busca}
              onChange={(event) => {
                setBusca(event.target.value);
                setProduto(null);
              }}
              placeholder="Ex.: arroz, refrigerante, pão francês"
              autoComplete="off"
            />
            {sugestoesVisiveis.length > 0 && (
              <ul className="simulador-sugestoes" role="listbox">
                {sugestoesVisiveis.map((item) => (
                  <li key={item.codigo_subitem}>
                    <button
                      type="button"
                      onClick={() => {
                        setProduto(item);
                        setBusca(item.nome);
                      }}
                    >
                      {item.nome} <small>{item.nome_grupo}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </label>
          <label>
            <span>Preço atual (R$)</span>
            <input
              value={preco}
              onChange={(event) => setPreco(event.target.value)}
              placeholder="12,50"
              inputMode="decimal"
            />
          </label>
          <label>
            <span>Estado</span>
            <select value={uf} onChange={(event) => setUf(event.target.value)}>
              {UFS.map((sigla) => (
                <option key={sigla}>{sigla}</option>
              ))}
            </select>
          </label>
          <button type="submit" className="simulador-botao" disabled={calculando}>
            {calculando ? "Calculando…" : "Calcular"}
          </button>
        </form>

        {erro && (
          <p className="simulador-erro" role="alert">
            {erro}
          </p>
        )}
        {resultado && (
          <div className="simulador-resultado" role="status">
            <span>
              Sugestão para {resultado.produto} em {monthLong(resultado.mes_previsto)}
            </span>
            <strong>{reais(resultado.preco_sugerido)}</strong>
            <span className={`simulador-confianca simulador-confianca-${resultado.confianca}`}>
              {resultado.confianca === "alta" ? "Confiança alta" : "Confiança baixa"}
            </span>
            {resultado.confianca === "baixa" && (
              <p className="simulador-alerta">
                Este item varia muito de um mês para o outro: o preço pode subir ou cair bem mais
                que o previsto. Use a sugestão como referência e acompanhe o preço do seu
                fornecedor.
              </p>
            )}
            <p>
              {resultado.confianca === "alta" && (
                <>
                  Provavelmente entre {reais(resultado.faixa_preco[0])} e{" "}
                  {reais(resultado.faixa_preco[1])}.{" "}
                </>
              )}
              {variacao(
                resultado.variacao_prevista_pct,
                "A alta prevista é de",
                "A queda prevista é de",
                "A previsão é de preço estável",
              )}{" "}
              ({resultado.praca}).
            </p>
            {resultado.ipca_12m_pct !== null && (
              <p>
                Nos últimos 12 meses, o preço de {resultado.produto.toLowerCase()}{" "}
                {variacao(resultado.ipca_12m_pct, "subiu", "caiu", "ficou estável")}.
              </p>
            )}
            <small>Estimativa a partir da inflação prevista; não é garantia.</small>
          </div>
        )}
        <button
          type="button"
          className="simulador-felicia"
          onClick={() => window.dispatchEvent(new Event("felicia:abrir"))}
        >
          Não achou seu produto? Pergunte à Felicia
        </button>
      </ChartPanel>

      <ChartPanel
        title={`O que deve subir mais no mês que vem em ${nomePraca}`}
        subtitle="Os 10 itens com maior alta prevista. Bom momento para rever esses preços."
      >
        {destaques === null ? (
          <p className="dashboard-panel-subtitle">Carregando…</p>
        ) : destaques.length === 0 ? (
          <p className="dashboard-panel-subtitle">Sem previsões publicadas para esta praça.</p>
        ) : (
          <ol className="destaques-lista">
            {destaques.map((item) => (
              <li key={item.codigo_subitem}>
                <span>
                  {item.nome} <small>{item.nome_grupo}</small>
                </span>
                <strong>{percentage(item.variacao_prevista_pct)}</strong>
              </li>
            ))}
          </ol>
        )}
      </ChartPanel>
    </div>
  );
}
