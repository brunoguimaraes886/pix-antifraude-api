# O motor de decisão — como plugar

O motor é a única parte que decide. Todo o resto da API existe para
entregar a ele, pronto, tudo que se sabe sobre um Pix, e para gravar o que
ele respondeu.

```
POST /pix/transaction
  → recusas operacionais (conta inexistente, bloqueada, sem saldo...)
  → resumo diário + DICT + histórico  ──►  Features
                                             │
                                   motor.evaluate(features)
                                             │
                                             ▼
                                        EngineResult(status, reasons, score)
  → grava a análise (status, motivos, latência, features, DICT)
  → approved? movimenta saldo e extrato
```

## O contrato

Tudo em `src/engine/`, sem nenhuma dependência de banco, HTTP ou relógio:

| Arquivo | O que tem |
|---|---|
| `features.py` | `Features`: a entrada do motor (dataclasses, com a descrição de cada campo) |
| `result.py` | `EngineResult(status, reasons, score)` e os três status |
| `reasons.py` | o catálogo de motivos (`Reason(code, message)`) |
| `base.py` | `FraudEngine`: a interface — um método, `evaluate(features) -> EngineResult` |
| `rules_engine.py` | o motor **provisório** (só vetos) |
| `__init__.py` | `get_engine()`: qual motor está em uso |

### Entrada: `Features`

| Bloco | O que responde |
|---|---|
| `transaction` | valor, data, hora local, período (`day`/`night`), valor ÷ saldo, ÷ renda, ÷ média e ÷ p90 de saída |
| `payer` | perfil (PF/PJ, idade, profissão, renda), idade da conta, saldo, limites, bloqueio em vigor, resumo diário (`baseline`), fluxo das últimas 24h, período atual e período anterior |
| `destination` | conta nossa ou de outro banco, idade da conta, PF/PJ, histórico de tudo que já chegou para ela, resposta do DICT (`ok` / `fallback` / `unavailable`) e — se for conta nossa — o mesmo bloco completo do pagador |
| `relationship` | o pagador já pagou esse destino? quanto, quantas vezes, em quantos dias; o destino já pagou o pagador? |
| `device` | aparelho e IP já usados? quantos aparelhos em 30 dias; distância e minutos desde o último Pix com localização |
| `velocity` | tentativas na última hora, 24h e no período (2FA e rejeitado contam) e segundos desde a última |

Cada janela de fluxo (`last_24h`, `current_period`, `previous_period`) traz:
entrada e saída (valor, quantidade, contrapartes distintas, **novas** — nunca
vistas antes da janela — e **repetidas** — 2+ vezes na janela), saldo no
início, **taxa de passagem** (saída ÷ entrada) e **razão de saída**
(saída ÷ (saldo no início + entrada)). Os períodos trazem também o `limit`
(diurno = `daily_limit`, noturno = `nightly_limit`).

Convenções: centavos (int), datas com fuso, proporções em float e `None`
quando não há base para a conta (sem histórico, divisão por zero) — "não
sei" é diferente de 0.

O `Features` inteiro fica gravado em `transaction_analysis.features`.
`Features.from_dict(...)` reconstrói o objeto a partir desse JSON: dá pra
reproduzir qualquer decisão antiga no motor novo.

### Saída: `EngineResult`

- `status`: `approved`, `two_factor_required` ou `rejected`
- `reasons`: lista de `Reason` (vazia no `approved` — a API garante)
- `score`: opcional; vai para `transaction_analysis.score`

Se o motor levantar exceção ou devolver um status inválido, a API não
aprova às cegas: responde `two_factor_required` com o motivo `engine_error`
e escreve o erro no log.

## Como trocar o motor

1. Escreva uma classe que herda de `FraudEngine` (ou acrescente regras na
   lista do `RulesEngine`).
2. Motivo novo? Acrescente um `Reason` em `reasons.py`.
3. Troque a linha do `get_engine()` em `src/engine/__init__.py`.

Nada fora de `src/engine/` precisa mudar.

## Como testar o motor sozinho

Os testes do motor são unitários e não precisam de Docker:

```bash
pytest tests/unit
```

`tests/unit/engine/features_factory.py` monta um `Features` de cliente
comum (`clean_features()`); cada teste altera só o campo da regra que
testa. Veja `tests/unit/engine/test_rules_engine.py`.
