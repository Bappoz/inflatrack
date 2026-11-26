"use client";

import { useState } from "react";

import { barWidth, monthLong, reais } from "./formato";
import type { AbaProps, DashboardData } from "./tipos";

type Ordem = "mais-caras" | "mais-baratas" | "a-z" | "z-a";
type Local = DashboardData["locations"][number];

const ORDENS: { id: Ordem; rotulo: string }[] = [
  { id: "mais-caras", rotulo: "Mais caras primeiro" },
  { id: "mais-baratas", rotulo: "Mais baratas primeiro" },
  { id: "a-z", rotulo: "Nome (A a Z)" },
  { id: "z-a", rotulo: "Nome (Z a A)" },
];

/** Quanto custam hoje R$ 100 de 12 meses atrás, dada a alta acumulada em 12 meses. */
function hoje(pct: number | null): number | null {
  return pct === null ? null : 100 * (1 + pct / 100);
}

function mesHaUmAno(ultimoMes: string): string {
  const [ano, mes] = ultimoMes.slice(0, 7).split("-");
  return monthLong(`${Number(ano) - 1}-${mes}-01`);
}

function Celula({ pct, maximo }: { pct: number | null; maximo: number }) {
  const valor = hoje(pct);
  return (
    <div className="location-bar-cell">
      <strong>{valor === null ? "—" : reais(valor)}</strong>
      <div className="dashboard-bar-track">
        {/* A barra mede a alta (o que passou de R$ 100): é onde as regiões diferem. */}
        <span
          className="dashboard-bar-fill"
          style={{ width: barWidth(pct, maximo) }}
        />
      </div>
    </div>
  );
}

export default function Pracas({ data, selectedIndex, accountState }: AbaProps) {
  const [ordem, setOrdem] = useState<Ordem>("mais-caras");
  // Ordena pelo índice escolhido no filtro; com os dois, pelo consumo amplo (IPCA).
  const valor = (local: Local) =>
    (selectedIndex === "INPC" ? local.inpc_12m_pct : local.ipca_12m_pct) ?? -Infinity;

  const brasil = data.locations.find((local) => local.localidade === "Brasil");
  const daConta = data.locations.filter(
    (local) => local !== brasil && !!accountState && local.uf?.toUpperCase() === accountState,
  );
  const demais = data.locations
    .filter((local) => local !== brasil && !daConta.includes(local))
    .sort((a, b) => {
      if (ordem === "mais-caras") return valor(b) - valor(a);
      if (ordem === "mais-baratas") return valor(a) - valor(b);
      const nome = a.localidade.localeCompare(b.localidade, "pt-BR");
      return ordem === "a-z" ? nome : -nome;
    });

  const mostrarIpca = selectedIndex !== "INPC";
  const mostrarInpc = selectedIndex !== "IPCA";
  const maximo = Math.max(
    0,
    ...data.locations.flatMap((local) => [local.ipca_12m_pct ?? 0, local.inpc_12m_pct ?? 0]),
  );
  const fixas = [
    ...(brasil ? [{ local: brasil, etiqueta: "REFERÊNCIA" }] : []),
    ...daConta.map((local) => ({ local, etiqueta: "SUA REGIÃO" })),
  ];
  const colunas = `pracas-colunas-${mostrarIpca && mostrarInpc ? 2 : 1}`;

  const linha = (local: Local, etiqueta?: string) => (
    <div
      className={`location-bar-row ${colunas}${etiqueta ? " location-bar-row-account" : ""}`}
      key={local.localidade}
    >
      <span className="location-bar-label">
        {local.localidade}
        {etiqueta && <small> {etiqueta}</small>}
      </span>
      {mostrarIpca && (
        <div className="pracas-ipca">
          <Celula pct={local.ipca_12m_pct} maximo={maximo} />
        </div>
      )}
      {mostrarInpc && (
        <div className="pracas-inpc">
          <Celula pct={local.inpc_12m_pct} maximo={maximo} />
        </div>
      )}
    </div>
  );

  return (
    <section className="dashboard-panel pracas">
      <div className="pracas-topo">
        <div>
          <h2>
            Um produto de R$ 100 em{" "}
            {data.latest_month ? mesHaUmAno(data.latest_month) : "12 meses atrás"} hoje custaria:
          </h2>
          <p className="dashboard-panel-subtitle">
            Consumo amplo (IPCA): a cesta média das famílias. Consumo básico (INPC): a cesta de
            quem ganha até 5 salários mínimos.
          </p>
        </div>
        <label className="pracas-ordem">
          <span>Ordenar</span>
          <select value={ordem} onChange={(event) => setOrdem(event.target.value as Ordem)}>
            {ORDENS.map((item) => (
              <option value={item.id} key={item.id}>
                {item.rotulo}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="location-bar-list pracas-lista">
        <div className={`location-bar-header ${colunas}`}>
          <span>Região</span>
          {mostrarIpca && <span>Consumo amplo (IPCA)</span>}
          {mostrarInpc && <span>Consumo básico (INPC)</span>}
        </div>
        {fixas.map(({ local, etiqueta }) => linha(local, etiqueta))}
        {demais.map((local) => linha(local))}
      </div>
    </section>
  );
}
