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

import { ChartPanel, monthLabel, reais, tooltipStyle } from "./formato";
import type { AbaProps } from "./tipos";

const margem = { top: 8, right: 14, left: 0, bottom: 4 };

function EixoMes() {
  return (
    <XAxis
      dataKey="mes_referencia"
      tickFormatter={monthLabel}
      minTickGap={30}
      stroke="var(--chart-muted)"
      tickLine={false}
    />
  );
}

export default function Relatorios({ data, selectedIndex }: AbaProps) {
  return (
    <div className="dashboard-grid">
      <ChartPanel
        title="A inflação ao longo do tempo"
        subtitle="Alta de preços acumulada em 12 meses, mês a mês."
      >
        <ResponsiveContainer width="100%" height={290}>
          <LineChart data={data.history} margin={margem}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            {EixoMes()}
            <YAxis
              tickFormatter={(value: number) => `${value}%`}
              stroke="var(--chart-muted)"
              tickLine={false}
            />
            <Tooltip
              labelFormatter={(value) => monthLabel(String(value))}
              formatter={(value, name) => [`${Number(value).toFixed(2)}%`, name]}
              contentStyle={tooltipStyle}
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

      <ChartPanel
        title="Meses em que os preços costumam subir mais"
        subtitle="Alta média de cada mês do ano, desde 2006. Útil para planejar reajustes e estoque."
      >
        <ResponsiveContainer width="100%" height={290}>
          <LineChart data={data.seasonality} margin={margem}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey="mes" stroke="var(--chart-muted)" tickLine={false} />
            <YAxis
              tickFormatter={(value: number) => `${value}%`}
              stroke="var(--chart-muted)"
              tickLine={false}
            />
            <Tooltip
              formatter={(value) => `${Number(value).toFixed(2)}%`}
              contentStyle={tooltipStyle}
            />
            <Legend />
            <Line dataKey="indice_geral_pct" name="Geral" stroke="var(--chart-mint)" dot={false} />
            <Line dataKey="alimentacao_pct" name="Alimentação" stroke="var(--chart-gold)" dot={false} />
            <Line dataKey="habitacao_pct" name="Habitação" stroke="var(--chart-lilac)" dot={false} />
            <Line dataKey="vestuario_pct" name="Vestuário" stroke="var(--chart-coral)" dot={false} />
            <Line dataKey="transportes_pct" name="Transportes" stroke="var(--chart-blue)" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartPanel>

      <ChartPanel
        title="Quanto valem hoje R$ 100 de 2006"
        subtitle={`O que R$ 100 compravam em janeiro de 2006, em dinheiro de cada mês.${
          data.purchasing_power_brasil ? " Dado do Brasil: o IBGE não publica esse índice por região." : ""
        }`}
      >
        <ResponsiveContainer width="100%" height={290}>
          <LineChart data={data.purchasing_power} margin={margem}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            {EixoMes()}
            <YAxis
              tickFormatter={(value: number) => `R$ ${value}`}
              stroke="var(--chart-muted)"
              tickLine={false}
            />
            <Tooltip
              labelFormatter={(value) => monthLabel(String(value))}
              formatter={(value) => [reais(Number(value)), "Poder de compra"]}
              contentStyle={tooltipStyle}
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

      {data.minimum_wage.length > 0 && (
        <ChartPanel
          title="Salário mínimo: o valor no papel x o que ele compra"
          subtitle="Salário mínimo de cada mês e o mesmo valor corrigido pela inflação até hoje (Brasil)."
        >
          <ResponsiveContainer width="100%" height={290}>
            <LineChart data={data.minimum_wage} margin={margem}>
              <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
              {EixoMes()}
              <YAxis
                tickFormatter={(value: number) => `R$ ${value}`}
                stroke="var(--chart-muted)"
                tickLine={false}
                width={70}
              />
              <Tooltip
                labelFormatter={(value) => monthLabel(String(value))}
                formatter={(value, name) => [reais(Number(value)), name]}
                contentStyle={tooltipStyle}
              />
              <Legend />
              <Line
                dataKey="salario_nominal"
                name="No papel"
                stroke="var(--chart-blue)"
                strokeWidth={2}
                dot={false}
              />
              <Line
                dataKey="salario_corrigido_pelo_ipca"
                name="Corrigido pela inflação"
                stroke="var(--chart-gold)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>
      )}
    </div>
  );
}
