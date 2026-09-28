# Dicionário de Dados

Uma página por fonte, descrevendo as tabelas que ela alimenta no banco. A caracterização da origem (volume, frequência, restrições) fica em [Fonte de Dados](../arquitetura/fonteDados.md).

| Fonte | Tabelas | Banco |
|---|---|---|
| [SIDRA/IBGE (IPCA e INPC)](sidra.md) | `fonte_agregado`, `variavel`, `localidade`, `classificacao`, `classificacao_versao`, `observacao` | PostgreSQL |
| [Transacional (Lojista)](transacional.md) | `lojista`, `produto`, `reajuste` | PostgreSQL |
| [PIB e Setores (SIDRA 1846)](pib.md) | `pib_setor`, `pib_valor` | DuckDB |
| [PIB da China (World Bank)](pib_china.md) | `pib_china` | DuckDB |
| [Macroeconomia (Dólar, Selic)](macroeconomia.md) | `dolar_cotacao`, `selic_taxa` | DuckDB |
| [Commodities e Energia (Alpha Vantage)](commodities.md) | `commodity`, `commodity_cotacao` | DuckDB |
| [Salário Mínimo e Cesta Básica (DIEESE)](salario_minimo.md) | `salario_minimo` | DuckDB |
| [Dados do Clima Diário (INMET)](clima.md) | `estacao_meteorologica`, `clima_diario` | DuckDB |
