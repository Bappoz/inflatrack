# Avaliação dos modelos de previsão do subitem — design

Data: 2026-11-19 · PR empilhado sobre o #23 (`feat/precos-atacadista`) · Branch `feat/modelo-reajuste`

## Por que

O modelo da E4 vai ajudar o lojista a decidir o reajuste do preço para acompanhar a variação
dos custos. O custo dele é o preço no atacado (`atacado.preco_atual`, ADR 0004), e o que o
modelo prevê é a **variação mensal do subitem do IPCA** desse produto no mês seguinte.

Antes de implementar a recomendação, a Squad precisa saber **se o modelo presta**. A
professora recomendou comparar o XGBoost com modelos básicos: **regressão linear** e
**regressão logarítmica**. Este PR é só essa avaliação. A recomendação em R$ e a gravação em
`public.recomendacao_reajuste` ficam para o PR seguinte.

## Objetivos

- Comparar cinco previsões da variação mensal do subitem em t+1, na mesma validação
  walk-forward e com as mesmas métricas:
  1. ingênua: último mês (`ŷ(t+1) = y(t)`);
  2. ingênua sazonal: mesmo mês do ano anterior (`ŷ(t+1) = y(t-11)`);
  3. regressão linear: `índice = a + b·t`;
  4. regressão logarítmica: `índice = a + b·ln(t)`;
  5. XGBoost com as variáveis da Gold.
- Um notebook Jupyter visual que mostra o resultado: tabela de MAE e RMSE por modelo, por
  grupo do IPCA e no geral, e gráficos de previsto contra real.
- Funções de modelo reaproveitáveis no PR seguinte, com testes.

## Não objetivos

- Gravar previsão ou recomendação em qualquer banco.
- Ativo ou job no Dagster: a avaliação é exploratória (decisão do integrante).
- As 9 regras da Seção 2.4 completas; entram só as que o escopo enxuto pede (abaixo).
- Ajuste fino de hiperparâmetros.

## Anti-objetivos

- **Vazar o futuro:** nenhuma variável do mês t+1 ou depois na previsão de t+1; nada ajustado
  com a série inteira (Seção 2.4, Regras 1 e 3).
- `train_test_split` aleatório (proibido na Seção 1).
- Preço em R$ no notebook ou no DuckDB: este PR não lê `atacado.preco`. Lê do Postgres só a
  lista de subitens de `atacado.produto`.

## Abordagens consideradas

1. **Módulo Python com relatório gerado e ativo no Dagster.** Recusada pelo integrante: o
   treino ainda é avaliação e não precisa estar orquestrado.
2. **Escolhida: notebook Jupyter**, mais visual para apresentar. *Decisão da ferramenta:* as
   funções (montar a série, ajustar cada modelo, walk-forward, métricas) ficam em
   `src/inflatrack/predicao/` com testes, e o notebook as importa. O motivo é que o PR
   seguinte reaproveita o modelo vencedor, e lógica só dentro de célula não se testa.

## Dados

- **Alvo:** `gold.fct_inflacao_mensal.variacao_mensal_pct`, `indice = 'IPCA'`.
- **Subitens:** os de `atacado.produto` (hoje 45, do atacadista de exemplo). Se o Postgres
  estiver fora do ar, o notebook usa os códigos de `data/atacado/tabela_exemplo.csv`.
- **Praça: Brasil (`codigo_localidade = 1`)**, decisão do integrante. Tem os 45 subitens com
  série completa no período de teste; Brasília, a praça do atacadista, teria só 39 (faltam
  fubá, farinha de trigo, sabão em barra, salsicha, leite em pó e margarina). As variáveis de
  clima do design já são nacionais (polos e El Niño), então nada se perde. Na fase de
  aplicação (PR seguinte), o modelo roda em todas as praças disponíveis. Por isso a praça é um
  parâmetro das funções, não uma constante enterrada.
- **Índice do subitem:** a Gold só traz número-índice para o IPCA geral do Brasil. O índice é
  montado encadeando `variacao_mensal_pct` (base 100 no primeiro mês da série).

## Modelos

- **Regressões linear e logarítmica:** em cada passo, ajustadas com `numpy.polyfit` sobre os
  **últimos 24 meses** do índice (`t = 1..24`). Projetam o índice em `t = 25`, e a previsão é
  `índice_previsto / índice_atual − 1`. *Decisão da ferramenta:* uma tendência de 20 anos não
  diz nada sobre o mês seguinte. A janela é uma constante.
- **XGBoost:** um modelo para todos os subitens juntos. As variáveis só usam o que existia em t:
  - variação de t, t−1 e t−2; médias móveis de 3, 6 e 12 meses; desvio de 12 meses (já na Gold);
  - mês do ano de t+1;
  - grupo do IPCA (2 primeiros dígitos) e o próprio subitem, como categorias;
  - El Niño / La Niña: intensidades e lags 3, 6, 9 e 12 de `fct_enso_mensal`, só com
    `mes_publicacao <= t`;
  - clima dos polos agrícolas por grupo de alimento (Seção 2.4, Regra 5), agregado num índice
    por grupo (anomalia de temperatura média e SPI-3 médio dos polos do grupo), só com
    `mes_fechado`. *Decisão da ferramenta:* só os subitens que a tabela da Regra 5 cobre
    (tubérculos e hortaliças, arroz e feijão, café, leite e derivados, óleos e carnes) recebem
    o índice; os outros (açúcar, frutas, massas, pães, bebidas, conservas, limpeza e higiene)
    ficam nulos, em vez de receber um polo por palpite;
  - dólar e Selic de `fct_macroeconomia_mensal`, quando houver (nulo antes; o XGBoost aceita).
  
  Hiperparâmetros fixos e conservadores (por exemplo, `max_depth=4`, `n_estimators=300`,
  `learning_rate=0.05`) e semente fixa.

## Validação

- Walk-forward com janela de treino **expansível**. Período de teste: os **últimos 36 meses**
  com IPCA divulgado (hoje nov/2023 a out/2026). A cada mês de teste, os 5 modelos são
  refeitos só com dados até t e preveem t+1.
- Métricas: MAE e RMSE em pontos percentuais, no geral, por grupo (alimentação, limpeza e
  higiene) e por subitem. Também o **ganho sobre a ingênua** (`1 − MAE_modelo / MAE_ingênua`).
- Regra 8: o XGBoost é avaliado com e sem clima. O clima fica só se melhorar o erro fora da
  amostra. *Decisão da ferramenta:* "clima" é o bloco inteiro (El Niño / La Niña + polos
  agrícolas). São duas variantes do XGBoost, e não quatro, para caber no prazo; separar o El
  Niño dos polos fica como próximo passo se o bloco ajudar.

## Entregáveis

- `src/inflatrack/predicao/serie.py`: lê a Gold (DuckDB só leitura) e monta a tabela de
  subitem × mês com o alvo e as variáveis, sem vazamento.
- `src/inflatrack/predicao/modelos.py`: as 5 previsões, com a mesma interface.
- `src/inflatrack/predicao/walk_forward.py`: o loop de validação e as métricas.
- `notebooks/avaliacao_modelos.ipynb`: executado e versionado com as saídas (tabelas e
  gráficos), para ser lido no GitHub sem rodar.
- `docs/evidencias/e4/avaliacao_modelos.md`: resumo com a tabela final e a conclusão.
- Dependências novas num grupo próprio do `uv` (`xgboost`, `matplotlib`, `jupyter`).
- Receita `just modelo-notebook`, que executa o notebook de ponta a ponta.

## Testes

- Vazamento: para cada linha de previsão de t+1, nenhuma variável vem de mês > t. Teste com
  uma série sintética em que o futuro tem um valor-sentinela.
- Regressões: numa série que cresce em linha reta, a linear acerta exato; numa série
  `a + b·ln(t)`, a logarítmica acerta.
- Ingênuas: valores conhecidos numa série pequena.
- Walk-forward: o modelo de cada passo só vê linhas com mês ≤ t.
- Métricas: MAE e RMSE contra valores calculados à mão.

## Fica para quem implementar

- A lista exata de polos por grupo, a partir da tabela da Regra 5.
- O formato dos gráficos.
