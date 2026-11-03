# ADR (numeração a definir) — Ingestão do banco do lojista: CDC lógico em vez de lote

- **Status:** adotado na E3
- **Data:** 2026-10-31
- **Decisores:** Lucas Zanetti (responsável pela fonte), para revisão da Squad

## Contexto

O lojista escreve no PostgreSQL (`lojista`, `produto`, `reajuste`, `reajuste_custo`, `venda_mensal`). A Gold precisa disso para comparar o preço dele com a inflação oficial (pergunta 5), e a E3 pede o histórico de cada mudança de preço e custo (SCD tipo 2). A pergunta é como levar essas mudanças à Bronze.

O que a escolha precisa garantir:

1. **Enxergar `UPDATE` e `DELETE`.** Renomear ou apagar um produto precisa virar evento.
2. **Não perder evento** com o coletor parado ou o banco reiniciado.
3. **Reprocessar sem duplicar**, e aceitar evento atrasado.
4. **O CNPJ não sair do Postgres** (LGPD).
5. **Nada que a Squad não consiga subir num `git clone`**: o monitor roda tudo com Docker e `uv`.

## Alternativas

**A. Lote com coluna de controle** (`where atualizado_em > ultima_carga`).

- ✅ Simples, sem configurar nada no banco.
- ❌ Não enxerga `DELETE`, e duas mudanças entre leituras viram uma só.
- ❌ As tabelas não têm `atualizado_em`, e relógio de aplicação não é uma ordem confiável.

**B. Foto completa e comparação** a cada execução.

- ✅ Enxerga tudo o que mudou de estado.
- ❌ Perde os estados intermediários, que são o próprio objeto do SCD2.
- ❌ O custo cresce com o tamanho da tabela, não com o volume de mudanças.

**C. Gatilhos gravando numa tabela de auditoria.**

- ✅ Sem depender de `wal_level`.
- ❌ Escreve na transação do lojista: uma falha na auditoria derruba o reajuste. Mais código para manter em cada tabela.

**D. CDC lógico com Debezium e Kafka.**

- ✅ Padrão de mercado, com vazão e tolerância a falhas muito acima do necessário.
- ❌ Dois serviços a mais (Kafka e Connect) e memória incompatível com o limite de 2 GB do compose, para um banco de poucas escritas por minuto.

**E. CDC lógico lendo o slot por função SQL** (`pg_logical_slot_peek_binary_changes`, plugin `pgoutput`). **← escolhida**

- ✅ Enxerga `INSERT`, `UPDATE`, `DELETE` e `TRUNCATE`, na ordem do WAL, com a linha anterior (`REPLICA IDENTITY FULL`).
- ✅ O slot segura o WAL enquanto ninguém lê: coletor parado não perde evento.
- ✅ Só o Postgres oficial: `pgoutput` é nativo, sem extensão nem serviço novo. A publicação lista as tabelas, e `serie` fica fora.
- ✅ Espiar sem consumir permite gravar primeiro e avançar o slot depois.
- ❌ O decodificador do protocolo binário é código nosso (coberto por testes unitários e por um Postgres real).
- ❌ Lote periódico, não fluxo: o evento chega na próxima execução (de hora em hora no agendamento).
- ❌ Slot esquecido retém WAL e pode encher o disco. Mitigação abaixo.

`psycopg` 3 não implementa o protocolo de streaming de replicação; a função SQL evita trocar de driver só por isso.

## Decisão

Opção **E**, em `src/inflatrack/cdc/transacional.py`, gravando em `data/parquet/transacional/mudanca/` e espelhada em `bronze.transacional_mudanca`.

- **Entrega ao menos uma vez + chave = efeito de exatamente uma vez.** A ordem é espiar, gravar no Delta e só então avançar o slot até o `end_lsn` do commit. Cair no meio relê os mesmos eventos, e a chave `(lsn, tabela, operacao, id_registro)` os ignora.
- **Tempo do negócio separado do tempo do sistema.** A Bronze guarda a ordem em que soube (`lsn`, `commit_em`). A Silver ordena reajustes por `aplicado_em`, então um evento atrasado entra na posição certa do histórico.
- **Primeira execução:** cria o slot e grava uma foto das tabelas (`operacao = 'r'`), porque o slot só vê o que vem depois dele.
- **LGPD:** em `lojista` passa só uma lista explícita de colunas, e o CNPJ vira `hash_estabelecimento` (HMAC-SHA256 com a chave `CDC_CHAVE_PSEUDONIMO`). Um SHA-256 sem chave seria revertido por força bruta, já que os CNPJs possíveis são poucos. `nome_fantasia` também fica de fora, porque nome de MEI costuma ser nome de pessoa.

## Consequências

- O banco precisa de `wal_level=logical` (no `docker-compose.yml`). Em volume já existente, é preciso recriar o contêiner e aplicar as migrations `0004` e `0005` (`just migrar <arquivo>`).
- **Risco operacional:** `max_slot_wal_keep_size=2GB` limita o WAL retido. Passado o limite, o slot é invalidado e o CDC falha com mensagem clara. A recuperação é apagar o slot e rodar de novo, o que refaz a foto; as mudanças do período ficam representadas pelo estado final, sem os passos intermediários.
- **Apagar o Delta exige apagar o slot:** com o slot vivo, a foto não é refeita e o estado anterior não volta.
- **É pseudonimização, não anonimização:** quem tem a chave consegue confirmar um CNPJ. O WAL e as tabelas do Postgres ainda contêm o dado. Trocar a chave muda todos os hashes, e o histórico deixa de se ligar ao novo. A análise completa é da E4 (LGPD).
- `TRUNCATE` é registrado, mas não afeta o histórico: a Silver o ignora.

## O que foi medido

Ver [Evidência E3 — IPCA, lojista e Gold](../evidencias/e3/ipca_lojista.md#cdc). A vazão não foi medida: o volume da demonstração (13 eventos) não sustenta nenhuma afirmação de desempenho.

## Reavaliar se

- Mais de um consumidor precisar das mudanças, ou a latência precisar cair para segundos: aí vale o Debezium.
- O banco deixar de ser nosso (Postgres gerenciado sem acesso a slot lógico).
