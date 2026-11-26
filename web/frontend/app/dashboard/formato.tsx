// Por padrão, a API é chamada pelo próprio site (/api, ver o rewrite em next.config.ts).
export const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "/api").replace(/\/$/, "");

const UM_DIA_MS = 24 * 60 * 60 * 1000;

/**
 * GET com cache de 24 h no navegador (localStorage): os dados mudam uma vez por mês.
 * `forcar` ignora o cache (botão de atualizar). Respostas com erro não entram no cache.
 * Sem localStorage (aba anônima, bloqueio), só busca. Devolve a Response quando não há cache.
 */
export async function getComCache(
  url: string,
  opcoes: { forcar?: boolean; signal?: AbortSignal } = {},
): Promise<{ status: number; ok: boolean; corpo: unknown }> {
  const chave = `inflatrack:${url}`;
  if (!opcoes.forcar) {
    try {
      const salvo = JSON.parse(localStorage.getItem(chave) ?? "null");
      if (salvo && Date.now() - salvo.em < UM_DIA_MS) return { status: 200, ok: true, corpo: salvo.corpo };
    } catch {
      // cache ilegível ou indisponível: segue para o servidor
    }
  }
  const resposta = await fetch(url, { credentials: "include", signal: opcoes.signal });
  const corpo = await resposta.json().catch(() => null);
  if (resposta.ok) {
    try {
      localStorage.setItem(chave, JSON.stringify({ em: Date.now(), corpo }));
    } catch {
      // sem espaço ou sem permissão: funciona sem cache
    }
  }
  return { status: resposta.status, ok: resposta.ok, corpo };
}

export const tooltipStyle = { background: "#ffffff", borderColor: "#ddd6e8", color: "#1c1822" };

export function percentage(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)}%`;
}

export function reais(value: number) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

export function monthLabel(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString("pt-BR", {
    month: "short",
    year: "2-digit",
  });
}

export function monthLong(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString("pt-BR", {
    month: "long",
    year: "numeric",
  });
}

export function barWidth(value: number | null, maximum: number) {
  if (value === null || maximum <= 0) return "0%";
  return `${Math.max(0, (value / maximum) * 100)}%`;
}

export type Tendencia = "subindo mais rápido" | "subindo mais devagar" | "no mesmo ritmo";

/** Compara o acumulado em 12 meses de agora com o de 3 meses antes (limiar de 0,2 p.p.). */
export function tendencia(
  history: { mes_referencia: string; ipca_12m_pct: number | null }[],
): Tendencia | null {
  const pontos = history.filter((ponto) => ponto.ipca_12m_pct !== null);
  if (pontos.length < 4) return null;
  const agora = pontos[pontos.length - 1].ipca_12m_pct as number;
  const antes = pontos[pontos.length - 4].ipca_12m_pct as number;
  if (agora - antes > 0.2) return "subindo mais rápido";
  if (antes - agora > 0.2) return "subindo mais devagar";
  return "no mesmo ritmo";
}

export function ChartPanel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="dashboard-panel">
      <h2>{title}</h2>
      {subtitle && <p className="dashboard-panel-subtitle">{subtitle}</p>}
      {children}
    </section>
  );
}
