# Putting the tables back together

```python
import transferegovpy as tg
import pandas as pd
```

Each API is a relational database published one table at a time. Nothing is
nested and nothing is pre-joined, so an analysis almost always means retrieving
two or three tables and joining them yourself. This page maps the keys.

## The shape of each module

Two identifiers do most of the work across all three modules:

* **`id_programa`** — the programme, which is the funding instrument as a whole.
* **`id_plano_acao`** — the action plan, which is one recipient's share of it.

Everything else hangs off one of those.

### TED

```
programa ──< plano_acao ──< plano_acao_meta ──< plano_acao_etapa
    │            ├──< termo_execucao
    ├──< programa_acao_orcamentaria
    └──< programa_beneficiario
                 ├──< nota_credito ──< evento
                 ├──< programacao_financeira ──< trf
                 ├──< plano_acao_analise
                 └──< plano_acao_parecer
```

`plano_acao_etapa` joins to `plano_acao_meta` on `id_meta`, not directly to the
plan. `trf` joins to `programacao_financeira` on `id_programacao`, and `evento`
to `nota_credito` on `id_nota`.

### Fund-to-fund

```
programa ──< plano_acao ──< plano_acao_meta ──< plano_acao_meta_acao
    │            ├──< empenho
    ├──< programa_beneficiario
    ├──< plano_acao_dado_bancario
    └──< programa_gestao_agil
                 ├──< plano_acao_destinacao_recursos
                 ├──< plano_acao_historico
                 ├──< termo_adesao ──< termo_adesao_historico
                 └──< relatorio_gestao ──< relatorio_gestao_acoes
                                        └──< relatorio_gestao_analise
```

The financial management tables form a chain of their own:
`gestao_financeira_lancamentos` joins to
`gestao_financeira_categorias_despesa` on
`id_categoria_despesa_gestao_financeira`, and `gestao_financeira_subtransacoes`
joins to the entries on `id_lancamento_gestao_financeira`.

Three tables across the APIs carry a foreign key with an `_fk` suffix rather
than an `id_` prefix: `plano_acao_analise_responsavel.plano_acao_analise_fk` and
`relatorio_gestao_analise_responsavel.relatorio_gestao_analise_fk` here, and
`plano_acao_parecer.plano_acao_hist_fk` in TED.

### Special transfers

```
programa_especial ──< plano_acao_especial ──< plano_trabalho_especial
                              ├──< executor_especial ──< meta_especial
                              │                      └──< finalidade_especial
                              ├──< empenho_especial ──< documento_habil_especial
                              ├──< relatorio_gestao_especial
                              └──< relatorio_gestao_novo_especial
```

`documento_habil_especial` leads on to
`ordem_pagamento_ordem_bancaria_especial` through `id_dh`, and from there to
`historico_pagamento_especial` through `id_op_ob`. That is the payment trail:
commitment, document, payment order, history.

Note that `meta_especial` and `finalidade_especial` hang off the *executor*
(`id_executor`), not off the plan.

## A worked example

Which federal bodies decentralize the most money, and to what?

```python
import math

programas = tg.get(
    "ted", "programa",
    select=["id_programa", "tx_nome_programa", "sigla_unidade_descentralizadora"],
    limit=math.inf,
)

planos = tg.get(
    "ted", "plano_acao",
    select=["id_plano_acao", "id_programa", "vl_total_plano_acao", "aa_ano_plano_acao"],
    limit=math.inf,
)

(
    planos.merge(programas, on="id_programa", how="inner")
    .groupby("sigla_unidade_descentralizadora")
    .agg(planos=("id_plano_acao", "size"), total=("vl_total_plano_acao", "sum"))
    .sort_values("total", ascending=False)
    .head()
)
```

| sigla_unidade_descentralizadora | planos | total |
|---|---:|---:|
| MDS | 229 | 422595208242 |
| MS | 794 | 14472373138 |
| FNDCT | 154 | 13779027285 |
| MIDR | 603 | 5450415783 |
| MAPA | 284 | 2835531350 |

Retrieving both tables in full is reasonable here — 5500 and 6176 rows, six
requests between them.

## Check the join, do not assume it

A join that quietly drops rows looks exactly like a join that worked. Count
before and after:

```python
(~planos["id_programa"].isin(programas["id_programa"])).sum()
# 0
```

Every action plan in TED belongs to a programme that is also published. That is
worth knowing rather than assuming, because it is not true of every key in
these APIs. Sampling two hundred values from each relationship above, most
resolve completely, but three do not:

| Child | Parent | Resolved |
|---|---|---|
| `meta_especial.id_executor` | `executor_especial.id_executor` | 175 / 200 |
| `finalidade_especial.id_executor` | `executor_especial.id_executor` | 175 / 200 |
| `programa_acao_orcamentaria.id_programa` | `programa.id_programa` | 198 / 200 |

These are gaps in what the platform publishes, not in the retrieval. An inner
join will drop those rows silently; use an anti-join to see them first, and
decide deliberately:

```python
orphans = planos[~planos["id_programa"].isin(programas["id_programa"])]
```

If you are joining a filtered subset, fetch the other side with a matching
filter rather than trimming afterwards:

```python
planos_2024 = tg.get(
    "ted", "plano_acao",
    aa_ano_plano_acao=2024,
    select=["id_plano_acao", "id_programa"],
    limit=math.inf,
)

notas = tg.get(
    "ted", "nota_credito",
    id_plano_acao=tg.in_(planos_2024["id_plano_acao"].tolist()),
    limit=math.inf,
)
```

`in_()` sends the whole set to the service, so the filtering happens there. A
very long list makes for a URL the service rejects — see
[the pagination guide](pagination.md#long-in_-lists) for the batching helper.

## Identifiers are nullable integers

Columns the API declares as `bigint` come back as pandas' nullable `Int64`,
which holds the full 64-bit range. Joins between them work as expected, since
both sides use the same dtype.

```python
planos.dtypes["id_plano_acao"]
# Int64
```

!!! note "Difference from the R sibling"
    `transferegovr` has to return these as a double, because R has no nullable
    integer that wide. If you compare results across the two packages, the
    values agree but the types do not.

## Repeated identifiers are real

Some of these tables are views with a join already baked in, so an identifier
that reads like a key can repeat. `fundoafundo/programa` has 129 rows but 125
distinct `id_programa`. Check before you use one as a key:

```python
programas_ff = tg.get("fundoafundo", "programa", limit=math.inf)

len(programas_ff), programas_ff["id_programa"].nunique()
# (129, 125)
```

`tables()` reports the primary key where the API declares one, which it does
for ten of the forty-eight tables. Where `primary_key` is `None`, no uniqueness
is guaranteed.

```python
tg.tables().dropna(subset=["primary_key"])
```
