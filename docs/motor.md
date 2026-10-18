# O motor de decisão por dentro

O motor é a única parte que decide. Todo o resto da API existe para
entregar a ele, pronto, tudo que se sabe sobre um Pix, e para gravar o que
ele respondeu. A especificação é o `4.2 - motor-pratica_claude.md` do repo
de contexto; este documento diz onde cada parte dela mora no código.

```
POST /pix/transaction
  → recusas operacionais (conta inexistente, bloqueada, sem saldo...)
  → resumo diário + histórico  ──►  Features (sem o DICT)
                                      │
                      ScorecardEngine.evaluate(features, consult_dict)
                        1. medidas + regras duras sem DICT → rejeitou? para aqui
                        2. consult_dict() → features.destination.dict
                        3. regras duras do DICT
                        4. sinais por família + assinaturas → pontos
                        5. pontos → P e ρ → política (com o piso das regras duras)
                        6. motivos, alerta, retenção, camada interna
                                      │
                                      ▼
                     EngineResult(status, reasons, score, alert, hold_recommended, decision)
  → liberação manual (se houver e o motivo for liberável)
  → grava a análise; approved? movimenta saldo e extrato
```

## Os arquivos

Tudo em `src/engine/`, sem abrir banco, HTTP ou relógio por conta própria.
O "agora" é a data do próprio Pix; a consulta ao DICT chega como função.

| Arquivo | O que tem | Seção do 4.2 |
|---|---|---|
| `features.py` | `Features`: a entrada do motor, com a descrição de cada campo | 4.2 |
| `params.py` | **todos** os pesos, limiares e custos | 14 |
| `measures.py` | medidas derivadas: p90 combinado (Bühlmann), fatia do saldo, razão de saída com o Pix, `inflow_jump`, dormência, aparelho cadastrado, idade das marcações do DICT | 4.1 |
| `hard_rules.py` | regras duras, em duas fases (antes e depois do DICT) | 3 |
| `signals/*.py` | um arquivo por família; cada sinal é uma função pura `(features, medidas) → Evidence` | 5 e 6 |
| `scoring.py` | tetos por família, piso dos mitigantes, P e ρ | 7 |
| `policy.py` | a política de custo | 8 |
| `response.py` | camada pública (motivos, alerta, retenção, sigilo de PLD) e interna (ameaça, causa, base, PLD) | 9 |
| `scorecard_engine.py` | junta tudo | 2 |
| `reasons.py` | o catálogo de motivos e mensagens; quais são sensíveis a PLD e quais não são liberáveis | — |
| `base.py`, `result.py` | a interface `FraudEngine` e o `EngineResult` | — |
| `__init__.py` | `get_engine()`: qual motor está em uso | — |

## O que a API monta para o motor

Os campos que o motor usa e de onde vêm (`src/controllers/feature_controller.py`):

| Campo | Origem |
|---|---|
| `payer.restricted_list`, `destination.restricted_list` | tabela `restricted_party` |
| `payer.unregistered_amount_today` | Pix aprovados hoje de aparelhos que não são cadastrados |
| `payer.unregistered_near_limit_24h` | Pix de R$ 180–200 de aparelho não cadastrado em 24h |
| `payer.baseline.night_out_share` | `account_baseline`: fração das saídas de 30 dias no período noturno |
| `relationship.same_owner` | CPF/CNPJ do destino = do pagador |
| `relationship.attempts_to_destination_24h`, `last_attempt_amount`, `blocked_attempts_24h`, `fraud_rejections_24h` | `pix_transaction` + análises das últimas 24h, sem recusas operacionais |
| `relationship.matching_recent_inflow` | extrato: entrada de contraparte nova, ±5% do valor, em 24h |
| `relationship.previous_in_amount`, `first_in_at` | extrato: o que o destino já pagou ao pagador |
| `destination.history.new_payers_7d` | outros clientes nossos cujo primeiro Pix para o destino (conta ou CPF/CNPJ) foi em 7 dias |
| `destination.history.fraud_rejected_payers_90d` | outros clientes com Pix para o destino rejeitado por suspeita sobre o destino (`decision.destination_evidence`) em 90 dias |
| `device.approved_days`, `first_approved_at`, `last_used_at`, `approved_devices_count` | `pix_transaction` aprovados por aparelho (aparelho cadastrado e cold start) |
| `device.other_accounts_last_30d`, `channel_previous_uses` | `pix_transaction` |

"Rejeitado por suspeita" = rejeitado com algum motivo que não é limite nem
operacional. É a mesma regra dos contadores do resumo diário.

## Saída: `EngineResult`

- `status`: `approved`, `two_factor_required` ou `rejected`.
- `reasons`: regras duras na ordem em que dispararam e depois os sinais, do
  maior para o menor, com os pontos. Vão para `analysis_reason`. A API zera
  a lista no `approved` (contrato da resposta).
- `score`: os pontos do Pix (`transaction_analysis.score`).
- `alert`, `hold_recommended`: a parte pública do alerta.
- `decision`: a camada interna (`transaction_analysis.decision`).

A resposta pública é montada no DTO a partir de `analysis_reason`
(`engine.response.public_reasons`): regras duras e os 3 sinais de maior
peso; os sensíveis a PLD viram `risk_policy`. A camada interna nunca sai.

Se o motor levantar exceção ou devolver um status inválido, a API não
aprova às cegas: responde `two_factor_required` com `engine_error`.

## Como calibrar

1. Os números estão todos em `params.py` (prior, c₂ = R$ 3, cortes de 10% e
   50%, ρ por família, tetos) e nos sinais (`signals/*.py`, os pontos de
   cada faixa).
2. Mudou um número? Rode `pytest tests/unit`: os cenários L e G
   (`tests/unit/engine/test_scenarios.py`) mostram que decisão mudou.
3. Para ver pontos, P e ρ de todos os cenários de uma vez:

```bash
python -c "import sys; sys.path.insert(0, 'src')
from tests.unit.engine.test_scenarios import SCENARIOS
from tests.unit.engine.engine_runner import evaluate
for name, build, _ in SCENARIOS:
    r = evaluate(build()); d = r.decision
    print(name, r.score, round(d.get('probability', 0) * 100, 2), d.get('rho'), r.status)"
```

4. Em produção, cada fraude confirmada (MED) e cada falso positivo
   recalculam o LR de cada sinal e os pontos viram `10 · log2(LR)`.

## Como trocar o motor

1. Escreva uma classe que herda de `FraudEngine`.
2. Motivo novo? Acrescente em `reasons.py` (sinais em `SIGNALS`).
3. Troque a linha do `get_engine()` em `src/engine/__init__.py`.

Nada fora de `src/engine/` precisa mudar.
