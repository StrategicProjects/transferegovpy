# Putting the tables back together

Each module is a normalized database served one table at a time. Almost nothing
useful is answerable from a single table: the money is in one, who received it
in another, and what it was spent on in a third. This page maps how they fit
together.

```python
import pandas as pd
import transferegovpy as tg
```

## The APIs do not declare their keys

The OpenAPI documents these services publish describe columns and query
parameters, and nothing else — no primary keys, no foreign keys. `fields()`
therefore cannot tell you what joins to what.

The relationships below come from the data models the government publishes
alongside the APIs. The convention is regular enough to follow without them: a
column named `id_x` in table B refers to the row of table X whose own `id_x`
matches.

## especiais

Everything hangs off the action plan, `planos_acao_especiais`.

```
programas_especiais ──< planos_acao_especiais >── beneficiarios_especiais
                              │
                              ├──< planos_trabalho_especiais
                              │        ├──< planos_trabalho_analises_especiais
                              │        ├──< planos_trabalho_historico
                              │        └──< orgaos_analises_pendentes_especiais
                              ├──< executores_especiais
                              │        ├──< meta_especiais
                              │        └──< finalidade_especiais
                              ├──< empenhos_especiais
                              │        └──< documentos_habeis_especiais
                              │                 └──< ordens_pagamentos_ordens_bancarias_especiais
                              ├──< planos_acao_historico_especiais
                              ├──< relatorios_gestao_especiais
                              ├──< devolucao_especiais
                              └──< relatorios_gestao_novos_especiais
                                       ├──< relatorios_gestao_analise_especiais
                                       └──< relatorios_gestao_documento_liquidacao_especiais
```

The three tables published in September 2026 — returned funds and the two
report tables under `relatorios_gestao_novos_especiais` — are not in the
government's data model yet. Their links were checked against the data
instead: every sampled identifier found its parent.

Note where the beneficiary lives. The action plan carries only
`id_beneficiario`; the name, CNPJ and state are in `beneficiarios_especiais`.
There is no way to filter action plans by state directly — you filter the
beneficiaries and join:

```python
import math

beneficiarios = tg.get("especiais", "beneficiarios_especiais", limit=math.inf)
pe = beneficiarios[beneficiarios["uf_beneficiario"] == "PE"]

planos = tg.get("especiais", "planos_acao_especiais", limit=math.inf)
planos = planos[planos["id_beneficiario"].isin(pe["id_beneficiario"])]
```

`beneficiarios_especiais` has five columns and is small enough to take whole,
which makes this cheaper than it looks.

## fundoafundo

Same shape, with the program at the top. Here the action plan does carry the
state, so a filter does the work the join would:

```python
planos = tg.get(
    "fundoafundo", "planos_acao",
    uf_ente_recebedor_plano_acao="PE",
    limit=math.inf,
)
```

## parcerias

The chain here is the longest, and it is the one worth following end to end: it
runs from the program that announces money to the bank statement of the account
it leaves from.

```
programa ──< proposta ──< parceria ──< parceria_conta ──< extrato_bancario
   │            │            │
   │            │            └──< documento_habil ──< ordem_pagamento
   │            │            └──< empenho_parceria
   │            ├──< meta_proposta
   │            ├──< item_proposta
   │            ├──< cronograma_desembolso
   │            └──< analise_proposta
   └──< beneficiario_emenda_parlamentar
             └──< indicacao_beneficiario_emenda_parlamentar
```

One link changes name on the way: `indicacao_beneficiario_emenda_parlamentar`
refers to its parent through `id_beneficiario_emenda_parlamentar`, which the
parent calls `id_beneficiario_emenda_parlamentar_programa`. The same
nominations also arrive nested in the parent, as `indicacoes_beneficiario`.

`opp` holds payment orders issued from a partnership's bank account — Pix
transfers, tax payments, bills — with the payee, the amount and whether it went
through. It is new and small: 137 rows between May and September 2026, 21 of
them described as tests (`"teste boleto"`, `"teste Pix cpf"`), so filter those
out before adding anything up. It hangs off the bank account, but not by the
account's own key:
it carries `id_conta_gf`, which matches the column of the same name in
`parceria_conta`, not `id_parceria_conta`. The difference matters because the
wrong join half-works: checked against the whole of `parceria_conta`, all of
`opp`'s accounts match on `id_conta_gf`, one row each, while two of the three
also coincide numerically with some unrelated `id_parceria_conta`. `opp` is in
no published data model yet, so the data is the only evidence.

```
parceria_conta ──< opp        (on id_conta_gf)
```

```python
propostas = tg.get(
    "parcerias", "proposta",
    sg_uf_recebedor="PE", situacao_proposta="Aprovada", limit=math.inf,
)

parcerias = tg.get("parcerias", "parceria", limit=math.inf)
parcerias = parcerias[parcerias["id_proposta"].isin(propostas["id_proposta"])]

contas = tg.get("parcerias", "parceria_conta", limit=math.inf)
contas = contas[contas["id_parceria"].isin(parcerias["id_parceria"])]
```

`extrato_bancario` holds 1.4 million rows, so join into it rather than
collecting it whole — filter by the accounts you care about.
`id_parceria_conta` takes up to 200 of them per request, so send them in
groups:

```python
ids = list(contas["id_parceria_conta"])

extratos = pd.concat(
    tg.get("parcerias", "extrato_bancario", id_parceria_conta=ids[i:i + 200],
           limit=math.inf)
    for i in range(0, len(ids), 200)
)
```

`params()` says which identifiers take a list, and how many values each
accepts, in its `multiple` and `max_values` columns.

## ted

Decentralized credit hangs off the action plan too, and the action plan off the
program. Every link below is declared in the government's data model, and each
was also checked against the data: of 200 identifiers sampled per link, every
one found exactly one parent row.

```
programas ──< planos_acao ──< termos_execucao
   │              │
   │              ├──< notas_credito ──< eventos
   │              ├──< programacoes_financeiras ──< programacoes_financeiras_trf
   │              ├──< planos_acao_metas ──< planos_acao_metas_etapas
   │              ├──< planos_trabalho_cronogramas
   │              ├──< planos_acao_analises
   │              └──< planos_acao_pareceres
   ├──< programas_acoes_orcamentarias
   └──< programas_beneficiarios
```

The join columns are `id_programa`, `id_plano_acao`, `id_nota`,
`id_programacao` and `id_meta`, each under the same name on both sides.

The identifiers here all take lists, so following the money from a set of plans
to the budget events of their credit notes is two requests per 200 plans rather
than one per plan:

```python
planos = tg.get("ted", "planos_acao", limit=200)

notas = tg.get("ted", "notas_credito",
               id_plano_acao=list(planos["id_plano_acao"]), limit=math.inf)

eventos = tg.get("ted", "eventos",
                 id_nota=list(notas["id_nota"].unique()[:200]), limit=math.inf)
```

## Children that arrive already joined

Several child tables have no endpoint. The API folds them into the parent as an
array, which means the join is already done and you only have to explode.

In `parcerias`: `ufs_habilitadas`, `programa_atende_a`, `categorias_despesa`,
`resultados_esperados` and `indicadores_programa` on `programa`;
`intervenientes_proposta` and `categorias_despesa_proposta` on `proposta`;
`etapas_proposta` on `meta_proposta`; `publicacoes_parceria` on `parceria`;
`classificacoes_ingresso` on `parceria_conta`; `tipos_analise` on
`analise_proposta`; `indicacoes_beneficiario` on
`beneficiario_emenda_parlamentar`; and `classificacao_despesa` on
`item_proposta`.

In `fundoafundo`: `programa_acao_orcamentaria` and `programa_natureza_despesa`
on `programas`, `categorias_despesa_lancamento` on
`gestao_financeira_lancamentos`, `categorias_despesa_subtransacao` on
`gestao_financeira_subtransacoes`, and `saldo_final_dado_bancario` on
`planos_acao_dados_bancarios`.

In `ted`: `esfera_orcamentaria_evento` and `natureza_despesa_evento` on
`eventos`, and `formalizacao_termo_execucao` and `link_termo_execucao` on
`termos_execucao`.

`especiais` has none: all twenty-three of its tables have endpoints.

To flatten one:

```python
programas = tg.get("parcerias", "programa", limit=math.inf)

ufs = (
    programas[["id_programa", "ufs_habilitadas"]]
    .explode("ufs_habilitadas")
    .dropna(subset=["ufs_habilitadas"])
)
ufs = ufs.join(pd.json_normalize(ufs.pop("ufs_habilitadas")).set_index(ufs.index))
```

`fields(nested=...)` tells you the shape before you explode:

```python
tg.fields("parcerias", "programa", nested="ufs_habilitadas")
```

## Joins that do not fully resolve

Not every identifier finds its parent. Government systems have rows that
predate a constraint, and rows whose parent has since been removed. Check
rather than assume:

```python
missing = ~planos["id_beneficiario"].isin(beneficiarios["id_beneficiario"])
missing.sum()
```

An inner join would drop those rows silently. Use a left join and count the
nulls, so a gap upstream shows up as a number rather than as a quietly smaller
answer.
