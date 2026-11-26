export type Aba = "geral" | "produtos" | "pracas" | "relatorios";

export type DashboardData = {
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
  /** true quando a praça não tem número-índice e a série é a do Brasil. */
  purchasing_power_brasil: boolean;
  minimum_wage: {
    mes_referencia: string;
    salario_nominal: number | null;
    salario_corrigido_pelo_ipca: number | null;
  }[];
};

export type DashboardUser = { id: string; email: string; nome: string; state?: string };

/** O que toda aba recebe do contêiner. */
export type AbaProps = {
  data: DashboardData;
  selectedIndex: string;
  nomePraca: string;
  accountState?: string;
};
