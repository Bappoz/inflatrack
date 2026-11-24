import { ChartPanel, barWidth, percentage, tendencia } from "./formato";
import type { AbaProps } from "./tipos";

export default function VisaoGeral({ data, selectedIndex, nomePraca }: AbaProps) {
  const ritmo = tendencia(data.history);
  const ipca = data.kpis.ipca_12m_pct;
  const maxSector = Math.max(0, ...data.sectors.map((sector) => sector.inflacao_12m_pct ?? 0));
  const setores = data.sectors.filter((sector) => sector.setor !== "Índice geral");

  return (
    <>
      <section className="dashboard-summary" aria-label="Resumo">
        <p>
          Em <strong>{nomePraca}</strong>, os preços subiram <strong>{percentage(ipca)}</strong>{" "}
          nos últimos 12 meses{ritmo ? <>, e estão <strong>{ritmo}</strong></> : null}.
        </p>
        {ritmo && (
          <small>Comparando com o acumulado de 12 meses de três meses atrás.</small>
        )}
      </section>

      <section className="dashboard-kpis" aria-label="Indicadores principais">
        {selectedIndex !== "INPC" && (
          <article className="kpi-card kpi-ipca">
            <span>IPCA · 12 meses</span>
            <strong>{percentage(data.kpis.ipca_12m_pct)}</strong>
            <small>A inflação oficial do país.</small>
          </article>
        )}
        {selectedIndex !== "IPCA" && (
          <article className="kpi-card kpi-inpc">
            <span>INPC · 12 meses</span>
            <strong>{percentage(data.kpis.inpc_12m_pct)}</strong>
            <small>A inflação das famílias que ganham até 5 salários mínimos.</small>
          </article>
        )}
      </section>

      <div className="dashboard-grid">
        <ChartPanel
          title="O que mais encareceu nos últimos 12 meses"
          subtitle="Alta de preços por setor, do maior para o menor."
        >
          <div className="sector-bar-list">
            {setores.map((sector) => (
              <div className="sector-bar-row" key={sector.setor}>
                <span className="sector-bar-label">{sector.setor}</span>
                <div className="dashboard-bar-track">
                  <span
                    className="dashboard-bar-fill sector-bar-fill"
                    style={{ width: barWidth(sector.inflacao_12m_pct, maxSector) }}
                  />
                </div>
                <strong>{percentage(sector.inflacao_12m_pct)}</strong>
              </div>
            ))}
          </div>
        </ChartPanel>
      </div>
    </>
  );
}
