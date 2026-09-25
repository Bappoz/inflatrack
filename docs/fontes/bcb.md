# Banco Central do Brasil (Macroeconomia)

Esta seção detalha a extração de dados macroeconômicos fundamentais para o projeto InflaTrack: o **Dólar Comercial** e a **Taxa SELIC**, ambos extraídos das APIs oficiais do Banco Central.

## 1. Visão Geral das Fontes

A flutuação da inflação para o lojista possui raízes diretas no câmbio (Dólar, impactando importações) e na taxa de juros (Selic, impactando crédito). O projeto consome os dados virgens nas fontes emissoras.

| Indicador | API / Sistema | Descrição Oficial | Frequência |
| :--- | :--- | :--- | :--- |
| **Dólar Comercial** | **Olinda (OData)** | Cotação de Compra e Venda do Dólar Americano | Diária (dias úteis) |
| **Taxa SELIC** | **SGS (Série 11)** | Taxa de juros - Selic efetiva | Diária (dias úteis) |

!!! abstract "Decisão Arquitetural (ADR)"
    Abandonamos o uso do SGS para o Dólar (que entregava apenas uma média genérica) e migramos para a API **Olinda**. A API Olinda entrega as colunas de "Compra" e "Venda" separadas. Isso é vital, pois o repasse de inflação que atinge o lojista importador de matérias-primas está diretamente atrelado ao Dólar de *Venda*.

---

## 2. Parâmetros de Ingestão e Segurança

Diferente de outras fontes (como o IBGE com limites de paginação), as APIs do Banco Central são públicas e resilientes.

*   **Autenticação:** Nenhuma (API Pública Aberta).
*   **WAF / Firewall:** Para evitar bloqueios `403 Forbidden` pelo Azure Front Door do BCB, as requisições incluem obrigatoriamente um cabeçalho `User-Agent` mascarado e são tratadas com tolerância a falhas.
*   **Limitações de Fuso/Data:** O SGS opera com datas `DD/MM/YYYY`, enquanto a Olinda exige o padrão americano `MM-DD-YYYY`. Nossos clientes Python isolam essa complexidade (`selic_sgs.py` e `dolar_olinda.py`), recebendo e orquestrando sempre o padrão ISO unificado (`YYYY-MM-DD`).

---

## 3. O Fluxo de Carga (Arquitetura Medallion / SOLID)

Seguindo os Princípios SOLID, dividimos a ingestão em scripts independentes, que executam a seguinte trilha até o banco analítico:

1.  **Aterrissagem RAW (`.json.gz`):** O script consome o payload das APIs e armazena os originais comprimidos na pasta `data/bcb_raw/`. Isso garante a imutabilidade e auditoria irrefutável do dado em caso de falha de transformação.
2.  **Transformação Bronze (`.parquet`):**
    *   **Remoção Intradiária:** Como a Olinda envia múltiplos boletins no mesmo dia, filtramos para manter apenas o **boletim de fechamento** (`keep="last"`).
    *   **Mitigação de Buracos Temporais:** As APIs do governo não abrem em finais de semana. Para evitar que *joins* futuros quebrem quando o lojista fizer uma venda num sábado, utilizamos a função `ffill()` do Pandas (Forward Fill). Ela estica o calendário e preenche sábados, domingos e feriados repetindo a última cotação útil da sexta-feira.
    *   O resultado é mantido em memória, sem gerar duplicação de arquivos no disco (cumprindo a regra do projeto de não persistir a camada Bronze sem necessidade).
3.  **Carga Silver (DuckDB):** Os próprios scripts de extração aplicam um `UPSERT` (via cláusula `ON CONFLICT DO UPDATE`) direto nas tabelas `dolar_cotacao` e `selic_taxa` do banco analítico local (`inflatrack.duckdb`). Isso garante que a carga seja matematicamente *idempotente* (não gera linhas duplicadas independentemente de quantas vezes o pipeline orquestrado pelo `justfile` for rodado).
