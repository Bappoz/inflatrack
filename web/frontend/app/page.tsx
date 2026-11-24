"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LogOut, RefreshCw } from "lucide-react";

import { apiUrl, getComCache, monthLabel } from "./dashboard/formato";
import Pracas from "./dashboard/pracas";
import Produtos from "./dashboard/produtos";
import Relatorios from "./dashboard/relatorios";
import type { Aba, DashboardData, DashboardUser } from "./dashboard/tipos";
import VisaoGeral from "./dashboard/visao-geral";

const ABAS: { id: Aba; rotulo: string; titulo: string }[] = [
  { id: "geral", rotulo: "Visão geral", titulo: "Como está a inflação na sua região" },
  { id: "produtos", rotulo: "Produtos", titulo: "Quanto cobrar no mês que vem" },
  { id: "pracas", rotulo: "Praças", titulo: "Sua região x o resto do país" },
  { id: "relatorios", rotulo: "Relatórios", titulo: "O histórico dos preços" },
];

export default function HomePage() {
  const router = useRouter();
  const [user, setUser] = useState<DashboardUser | null>(null);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  // O botão de atualizar pula o cache de 24 h só na próxima busca.
  const ignorarCache = useRef(false);
  const [selectedLocation, setSelectedLocation] = useState("1");
  // A região da conta só é escolhida sozinha no primeiro carregamento;
  // depois disso, "Brasil" escolhido pelo usuário fica como está.
  const regiaoDaContaAplicada = useRef(false);
  const [selectedPeriod, setSelectedPeriod] = useState("60");
  const [selectedIndex, setSelectedIndex] = useState("Ambos");
  const [aba, setAba] = useState<Aba>("geral");

  useEffect(() => {
    let active = true;

    async function loadDashboard() {
      setLoading(true);
      setError("");

      try {
        const baseUrl = apiUrl;
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
        const dashboardResponse = await getComCache(
          `${baseUrl}/dashboard?${dashboardParams.toString()}`,
          { forcar: ignorarCache.current },
        );
        ignorarCache.current = false;
        const result = dashboardResponse.corpo as DashboardData & { detail?: string };
        if (dashboardResponse.status === 401) {
          router.replace("/login");
          return;
        }
        if (!dashboardResponse.ok) {
          throw new Error(result?.detail ?? "Não foi possível carregar o dashboard.");
        }
        if (active) {
          const dashboardData = result as DashboardData;
          setData(dashboardData);
          const primeiraCarga = !regiaoDaContaAplicada.current;
          regiaoDaContaAplicada.current = true;
          if (primeiraCarga && selectedLocation === "1" && currentUser.state) {
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
    await fetch(`${apiUrl}/auth/logout`, {
      method: "POST",
      credentials: "include",
    }).catch(() => null);
    router.replace("/login");
  }

  const accountState = user?.state?.trim().toUpperCase();
  const selectedOption = data?.location_options.find(
    (option) => String(option.codigo_localidade) === selectedLocation,
  );
  const nomePraca = selectedOption?.nome_localidade ?? "Brasil";
  const regionLabel =
    selectedLocation === "1"
      ? accountState
        ? `BRASIL · SEU ESTADO ${accountState}`
        : "BRASIL"
      : `${nomePraca.toUpperCase()}${selectedOption?.uf ? ` · ${selectedOption.uf.toUpperCase()}` : ""}`;
  const abaAtual = ABAS.find((item) => item.id === aba) ?? ABAS[0];

  return (
    <main className="dashboard-page">
      <div className="dashboard-content">
        <header className="dashboard-topbar">
          <nav className="dashboard-tabs" aria-label="Seções do painel" role="tablist">
            {ABAS.map((item) => (
              <button
                type="button"
                role="tab"
                aria-selected={aba === item.id}
                className={`dashboard-tab${aba === item.id ? " dashboard-tab-active" : ""}`}
                key={item.id}
                onClick={() => setAba(item.id)}
              >
                {item.rotulo}
              </button>
            ))}
          </nav>
        </header>
        <section className="dashboard-heading">
          <div>
            <p className="dashboard-eyebrow">
              {abaAtual.rotulo.toUpperCase()} · {regionLabel}
            </p>
            <h1>{user ? `Olá, ${user.nome}!` : "Olá!"}</h1>
            <p className="dashboard-subtitle">
              {abaAtual.titulo}.
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
              onClick={() => {
                ignorarCache.current = true;
                setReloadKey((key) => key + 1);
              }}
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

        {/* Na aba Produtos o estado do simulador já escolhe a região: sem filtros. */}
        {data && aba !== "produtos" && (
          <section
            className="dashboard-filters"
            aria-label="Filtros do dashboard"
          >
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
            <span>Confira se o dashboard_job já publicou os dados no Supabase.</span>
          </div>
        ) : !data?.latest_month ? (
          <div className="dashboard-state">
            <strong>Ainda não há dados publicados</strong>
            <p>Rode o dashboard_job no Dagster para publicar os dados no Supabase.</p>
          </div>
        ) : aba === "produtos" ? (
          <Produtos pracas={data.location_options} ufConta={accountState ?? null} />
        ) : (
          (() => {
            const props = { data, selectedIndex, nomePraca, accountState };
            if (aba === "pracas") return <Pracas {...props} />;
            if (aba === "relatorios") return <Relatorios {...props} />;
            return <VisaoGeral {...props} />;
          })()
        )}

        <footer className="dashboard-footer">
          <span>Fonte: IBGE · IPCA e INPC</span>
          <span>Previsões do modelo InflaTrack</span>
        </footer>
      </div>
    </main>
  );
}