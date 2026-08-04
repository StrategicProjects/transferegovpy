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
                              └──< relatorios_gestao_novos_especiais
```

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

`extrato_bancario` holds over a million rows, so join into it rather than
collecting it whole — filter by the account you care about:

```python
extratos = pd.concat(
    tg.get("parcerias", "extrato_bancario", id_parceria_conta=int(i), limit=math.inf)
    for i in contas["id_parceria_conta"]
)
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
`gestao_financeira_lancamentos`, and `categorias_despesa_subtransacao` on
`gestao_financeira_subtransacoes`.

`especiais` has none: all twenty of its tables have endpoints.

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
