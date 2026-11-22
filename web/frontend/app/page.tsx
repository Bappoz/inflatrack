"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bell,
  LogOut,
  RefreshCw,
  Search,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type DashboardData = {
  latest_month: string | null;
  location_options: { codigo_localidade: number; nome_localidade: string; uf: string | null }[];
  kpis: {
    ipca_12m_pct: number | null;
    inpc_12m_pct: number | null;
  };
  sectors: { setor: string; inflacao_12m_pct: number | null }[];
  locations: {
    localidade: string;
    uf: string | null;
    ipca_12m_pct: number | null;
    inpc_12m_pct: number | null;
  }[];
  history: { mes_referencia: string; ipca_12m_pct: number | null; inpc_12m_pct: number | null }[];
  seasonality: {
    mes_numero: number;
    mes: string;
    indice_geral_pct: number | null;
    alimentacao_pct: number | null;
    habitacao_pct: number | null;
    vestuario_pct: number | null;
    transportes_pct: number | null;
  }[];
  purchasing_power: { mes_referencia: string; poder_compra_100_reais: number | null }[];
};

type DashboardUser = { id: string; email: string; nome: string; state?: string };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function percentage(value: number | null) {
  if (value === null) return "—";
  return `${new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)}%`;
}

function monthLabel(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString("pt-BR", {
    month: "short",
    year: "2-digit",
  });
}

function barWidth(value: number | null, maximum: number) {
  if (value === null || maximum <= 0) return "0%";
  return `${Math.max(0, (value / maximum) * 100)}%`;
}

function ChartPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="dashboard-panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<DashboardUser | null>(null);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedLocation, setSelectedLocation] = useState("1");
  const [selectedPeriod, setSelectedPeriod] = useState("60");
  const [selectedIndex, setSelectedIndex] = useState("Ambos");

  useEffect(() => {
    let active = true;

    async function loadDashboard() {
      setLoading(true);
      setError("");

      try {
        const baseUrl = apiUrl.replace(/\/$/, "");
        const userResponse = await fetch(`${baseUrl}/auth/me`, { credentials: "include" });
        if (userResponse.status === 401) {
          router.replace("/login");
          return;
        }
        const currentUser = await userResponse.json();
        if (!userResponse.ok) {
          throw new Error(currentUser.detail ?? "Não foi possível validar sua sessão.");
        }
        if (active) setUser(currentUser as DashboardUser);

        const dashboardParams = new URLSearchParams({
          localidade: selectedLocation,
          periodo: selectedPeriod,
          indice: selectedIndex,
        });
        const dashboardResponse = await fetch(
          `${baseUrl}/dashboard?${dashboardParams.toString()}`,
          { credentials: "include" },
        );
        const result = await dashboardResponse.json();
        if (dashboardResponse.status === 401) {
          router.replace("/login");
          return;
        }
        if (!dashboardResponse.ok) {
          throw new Error(result.detail ?? "Não foi possível carregar o dashboard.");
        }
        if (active) {
          const dashboardData = result as DashboardData;
          setData(dashboardData);
          if (selectedLocation === "1" && currentUser.state) {
            const accountLocation = dashboardData.location_options.find(
              (option) =>
                option.uf?.toUpperCase() === String(currentUser.state).toUpperCase(),
            );
            if (accountLocation) setSelectedLocation(String(accountLocation.codigo_localidade));
          }
        }
      } catch (loadError) {
        if (active) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "Não foi possível conectar à API do dashboard.",
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadDashboard();
    return () => {
      active = false;
    };
  }, [reloadKey, router, selectedLocation, selectedPeriod, selectedIndex]);

  async function handleLogout() {
    await fetch(`${apiUrl.replace(/\/$/, "")}/auth/logout`, {
      method: "POST",
      credentials: "include",
    }).catch(() => null);
    router.replace("/login");
  }

  const ipca = data?.kpis.ipca_12m_pct;
  const inpc = data?.kpis.inpc_12m_pct;
  const spread = typeof ipca === "number" && typeof inpc === "number" ? ipca - inpc : null;
  const maxSectorInflation = Math.max(
    0,
    ...(data?.sectors ?? []).map((sector) => sector.inflacao_12m_pct ?? 0),
  );
  const maxLocationInflation = Math.max(
    0,
    ...(data?.locations ?? []).flatMap((location) => [
      location.ipca_12m_pct ?? 0,
      location.inpc_12m_pct ?? 0,
    ]),
  );
  const accountState = user?.state?.trim().toUpperCase();
  const orderedLocations = [...(data?.locations ?? [])].sort((left, right) => {
    const leftMatches = left.uf?.toUpperCase() === accountState;
    const rightMatches = right.uf?.toUpperCase() === accountState;
    if (leftMatches !== rightMatches) return leftMatches ? -1 : 1;
    return left.localidade.localeCompare(right.localidade, "pt-BR");
  });

  return (
    <main className="dashboard-page">
      <div className="dashboard-content">
        <header className="dashboard-topbar">
          <nav className="dashboard-tabs" aria-label="Seções do painel">
            <button type="button" className="dashboard-tab dashboard-tab-active">Visão geral</button>
            <button type="button" className="dashboard-tab">Indicadores</button>
            <button type="button" className="dashboard-tab">Praças</button>
            <button type="button" className="dashboard-tab">Relatórios</button>
          </nav>
        </header>
        <section className="dashboard-heading">
          <div>
            <p className="dashboard-eyebrow">
              VISÃO GERAL · {accountState ? `REGIÃO ${accountState}` : "BRASIL"}
            </p>
            <h1>{user ? `Olá, ${user.nome}!` : "Olá!"}</h1>
            <p className="dashboard-subtitle">
              Acompanhe os indicadores econômicos publicados pelo pipeline.
            </p>
          </div>
          <div className="dashboard-heading-meta">
            {data?.latest_month && (
              <span>Último mês: {monthLabel(data.latest_month)}</span>
            )}
            <button
              className="refresh-button"
              type="button"
              aria-label="Atualizar dashboard"
              title="Atualizar dashboard"
              onClick={() => setReloadKey((key) => key + 1)}
              disabled={loading}
            >
              <RefreshCw aria-hidden="true" size={16} />
            </button>
            <button
              className="dashboard-logout-button"
              type="button"
              aria-label="Sair"
              title="Sair"
              onClick={handleLogout}
            >
              <LogOut aria-hidden="true" size={16} />
            </button>
          </div>
        </section>

        {data && (
          <section className="dashboard-filters" aria-label="Filtros do dashboard">
            <label>
              <span>Praça</span>
              <select
                value={selectedLocation}
                onChange={(event) => setSelectedLocation(event.target.value)}
              >
                {data.location_options.map((option) => (
                  <option value={option.codigo_localidade} key={option.codigo_localidade}>
                    {option.nome_localidade}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Período</span>
              <select
                value={selectedPeriod}
                onChange={(event) => setSelectedPeriod(event.target.value)}
              >
                <option value="12">Últimos 12 meses</option>
                <option value="24">Últimos 24 meses</option>
                <option value="60">Últimos 5 anos</option>
                <option value="0">Todo o histórico</option>
              </select>
            </label>
            <label>
              <span>Índice</span>
              <select
                value={selectedIndex}
                onChange={(event) => setSelectedIndex(event.target.value)}
              >
                <option value="Ambos">IPCA e INPC</option>
                <option value="IPCA">IPCA</option>
                <option value="INPC">INPC</option>
              </select>
            </label>
          </section>
        )}

        {loading ? (
          <div className="dashboard-state" role="status">Carregando dados do pipeline…</div>
        ) : error ? (
          <div className="dashboard-state dashboard-state-error" role="alert">
            <strong>Dados indisponíveis</strong>
            <p>{error}</p>
            <span>Confira o PostgreSQL e execute os ativos da Dagster até `serie_postgres`.</span>
          </div>
        ) : !data?.latest_month ? (
          <div className="dashboard-state">
            <strong>A vitrine ainda não tem dados</strong>
            <p>Execute o pipeline da Dagster para publicar os modelos Gold em `serie`.</p>
          </div>
        ) : (
          <>
            <section className="dashboard-kpis" aria-label="Indicadores principais">
              {selectedIndex !== "INPC" && (
                <article className="kpi-card kpi-ipca">
                  <span>IPCA · 12 meses</span>
                  <strong>{percentage(data.kpis.ipca_12m_pct)}</strong>
                  <small>{selectedLocation === "1" ? "Brasil" : "Praça selecionada"} · índice geral</small>
                </article>
              )}
              {selectedIndex !== "IPCA" && (
                <article className="kpi-card kpi-inpc">
                  <span>INPC · 12 meses</span>
                  <strong>{percentage(data.kpis.inpc_12m_pct)}</strong>
                  <small>{selectedLocation === "1" ? "Brasil" : "Praça selecionada"} · índice geral</small>
                </article>
              )}
              {selectedIndex === "Ambos" && (
                <article className="kpi-card kpi-spread">
                  <span>Diferença IPCA − INPC</span>
                  <strong>{percentage(spread)}</strong>
                  <small>pontos percentuais · {selectedLocation === "1" ? "Brasil" : "praça selecionada"}</small>
                </article>
              )}
            </section>

            <div className="dashboard-grid">
              <ChartPanel title="Inflação acumulada em 12 meses por setor">
                <div className="sector-bar-list">
                  {data.sectors.map((sector) => (
                    <div className="sector-bar-row" key={sector.setor}>
                      <span className="sector-bar-label">{sector.setor}</span>
                      <div className="dashboard-bar-track">
                        <span
                          className="dashboard-bar-fill sector-bar-fill"
                          style={{ width: barWidth(sector.inflacao_12m_pct, maxSectorInflation) }}
                        />
                      </div>
                      <strong>{percentage(sector.inflacao_12m_pct)}</strong>
                    </div>
                  ))}
                </div>
              </ChartPanel>

              <ChartPanel title="IPCA e INPC em 12 meses por praça">
                <div className="location-bar-list">
                  <div className="location-bar-header">
                    <span>Localidade</span>
                    <span>IPCA</span>
                    <span>INPC</span>
                  </div>
                  {orderedLocations.map((location) => {
                    const isAccountRegion = location.uf?.toUpperCase() === accountState;
                    return (
                    <div
                      className={`location-bar-row${isAccountRegion ? " location-bar-row-account" : ""}`}
                      key={location.localidade}
                      title={isAccountRegion ? "Região cadastrada na sua conta" : undefined}
                    >
                      <span className="location-bar-label">
                        {location.localidade}
                        {isAccountRegion && <small> SUA REGIÃO</small>}
                      </span>
                      <div className="location-bar-cell">
                        <strong>{percentage(location.ipca_12m_pct)}</strong>
                        <div className="dashboard-bar-track">
                          <span
                            className="dashboard-bar-fill location-ipca-fill"
                            style={{ width: barWidth(location.ipca_12m_pct, maxLocationInflation) }}
                          />
                        </div>
                      </div>
                      <div className="location-bar-cell">
                        <strong>{percentage(location.inpc_12m_pct)}</strong>
                        <div className="dashboard-bar-track">
                          <span
                            className="dashboard-bar-fill location-inpc-fill"
                            style={{ width: barWidth(location.inpc_12m_pct, maxLocationInflation) }}
                          />
                        </div>
                      </div>
                    </div>
                    );
                  })}
                </div>
              </ChartPanel>

              <ChartPanel title="IPCA x INPC · últimos 5 anos">
                <ResponsiveContainer width="100%" height={290}>
                  <LineChart data={data.history} margin={{ top: 8, right: 14, left: 0, bottom: 4 }}>
                    <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                    <XAxis
                      dataKey="mes_referencia"
                      tickFormatter={monthLabel}
                      minTickGap={30}
                      stroke="var(--chart-muted)"
                      tickLine={false}
                    />
                    <YAxis
                      tickFormatter={(value: number) => `${value}%`}
                      stroke="var(--chart-muted)"
                      tickLine={false}
                    />
                    <Tooltip
                      labelFormatter={(value) => monthLabel(String(value))}
                      formatter={(value, name) => [`${Number(value).toFixed(2)}%`, name]}
                      contentStyle={{
                        background: "#ffffff",
                        borderColor: "#ddd6e8",
                        color: "#1c1822",
                      }}
                    />
                    <Legend />
                    {selectedIndex !== "INPC" && (
                      <Line
                        dataKey="ipca_12m_pct"
                        name="IPCA"
                        stroke="var(--chart-gold)"
                        strokeWidth={2}
                        dot={false}
                        connectNulls
                      />
                    )}
                    {selectedIndex !== "IPCA" && (
                      <Line
                        dataKey="inpc_12m_pct"
                        name="INPC"
                        stroke="var(--chart-lilac)"
                        strokeWidth={2}
                        dot={false}
                        connectNulls
                      />
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </ChartPanel>

              <ChartPanel title="Sazonalidade · variação média por mês">
                <ResponsiveContainer width="100%" height={290}>
                  <LineChart data={data.seasonality} margin={{ top: 8, right: 14, left: 0, bottom: 4 }}>
                    <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                    <XAxis dataKey="mes" stroke="var(--chart-muted)" tickLine={false} />
                    <YAxis
                      tickFormatter={(value: number) => `${value}%`}
                      stroke="var(--chart-muted)"
                      tickLine={false}
                    />
                    <Tooltip
                      formatter={(value) => `${Number(value).toFixed(2)}%`}
                      contentStyle={{
                        background: "#ffffff",
                        borderColor: "#ddd6e8",
                        color: "#1c1822",
                      }}
                    />
                    <Legend />
                    <Line dataKey="indice_geral_pct" name="Índice geral" stroke="var(--chart-mint)" dot={false} />
                    <Line dataKey="alimentacao_pct" name="Alimentação" stroke="var(--chart-gold)" dot={false} />
                    <Line dataKey="habitacao_pct" name="Habitação" stroke="var(--chart-lilac)" dot={false} />
                    <Line dataKey="vestuario_pct" name="Vestuário" stroke="var(--chart-coral)" dot={false} />
                    <Line dataKey="transportes_pct" name="Transportes" stroke="var(--chart-blue)" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </ChartPanel>

              <ChartPanel title="Poder de compra de R$ 100 desde jan/2006">
                <ResponsiveContainer width="100%" height={290}>
                  <LineChart data={data.purchasing_power} margin={{ top: 8, right: 14, left: 0, bottom: 4 }}>
                    <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                    <XAxis
                      dataKey="mes_referencia"
                      tickFormatter={monthLabel}
                      minTickGap={30}
                      stroke="var(--chart-muted)"
                      tickLine={false}
                    />
                    <YAxis
                      tickFormatter={(value: number) => `R$ ${value}`}
                      stroke="var(--chart-muted)"
                      tickLine={false}
                    />
                    <Tooltip
                      labelFormatter={(value) => monthLabel(String(value))}
                      formatter={(value) => [`R$ ${Number(value).toFixed(2)}`, "Poder de compra"]}
                      contentStyle={{
                        background: "#ffffff",
                        borderColor: "#ddd6e8",
                        color: "#1c1822",
                      }}
                    />
                    <Line
                      dataKey="poder_compra_100_reais"
                      name="Poder de compra"
                      stroke="var(--chart-coral)"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </ChartPanel>
            </div>
          </>
        )}

        <footer className="dashboard-footer">
          <span>Fonte: IBGE · IPCA e INPC</span>
          <span>Dados publicados pela Dagster em `serie`</span>
        </footer>
      </div>
    </main>
  );
}