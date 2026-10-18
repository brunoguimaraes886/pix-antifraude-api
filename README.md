# Pix Antifraude — Hacka QI

**Integrantes:** Bruno Guimarães Duarte, Ana

API que recebe um Pix, decide se ele pode sair (`approved`,
`two_factor_required` ou `rejected`) e grava tudo que chegou. Feita a
partir do Base Service do Bootcamp QI Tech: Python + FastAPI, PostgreSQL,
Docker, com as mesmas camadas (resource → controller → repository).

> **Estado atual:** API e motor completos. O motor (`src/engine/`) segue a
> proposta do `4.2 - motor-pratica`: regras duras → medidas → sinais em
> pontos → probabilidade → decisão por custo. Os pesos e custos são
> premissas de especialista, todos em `src/engine/params.py`, e ainda vão
> ser calibrados. Detalhes em [docs/motor.md](docs/motor.md).

---

## Como o motor de decisão funciona

Uma transação sozinha diz pouco. A API compara o Pix com o que o pagador e
o destino já fizeram antes e entrega isso pronto ao motor:

```
POST /pix/transaction
  1. já recebido?             → devolve a análise gravada (idempotente)
  2. trava as contas          → saldo e limite lidos sem corrida
  3. grava o Pix              → tudo que chega fica no banco, inclusive o rejeitado
  4. recusas operacionais     → conta inexistente, bloqueada, sem saldo...
  5. resumo diário            → o "habitual" da conta (30 dias), 1x por dia
  6. features                 → pagador, destino, relação, aparelho, ritmo (sem o DICT)
  7. motor                    → regras duras; se não rejeitam, DICT (ou fallback),
                                sinais, pontos, probabilidade e decisão
  8. liberação manual         → barrado por suspeita e liberado? aprova
  9. grava a análise          → status, motivos com pontos, latência, features,
                                DICT e a camada interna da decisão
 10. approved?                → debita, credita (se o destino é nosso) e lança no extrato
```

**Quem é analisado.** Só Pix que sai de um cliente nosso. Quem recebe pode
ser cliente nosso (mesmo ISPB, `88888888`) — aí o motor vê o perfil
completo dela — ou de outro banco — aí vê o que temos: DICT, idade da
conta (`opening_date` do payload) e tudo que já chegou aqui com ela como
destino, de qualquer cliente nosso.

### As quatro perguntas

Toda fraude responde "não" a pelo menos uma. A resposta muda o que funciona
contra ela: ρ é a fração da fraude que o 2FA barraria.

| Pergunta | Ameaça | Família de sinais | O 2FA resolve? (ρ) |
|---|---|---|---|
| Quem opera é o dono? | invasão de conta | `identity` | sim (0,9) |
| O dono age por vontade própria? | golpe, coação | `magnitude`, `velocity`, `relationship`, `context` | pouco (0,3–0,4) |
| O destino é confiável? | laranja no destino | `destination` | não (0,1) |
| O pagador repassa dinheiro de outros? | laranja no pagador | `payer_mule` | não (0,1) |

### Regras duras (não passam pelo score)

| Regra | Decisão | Quando |
|---|---|---|
| `sanctioned_party` | `rejected` | pagador ou destino na lista do CSNU (`restricted_party`) |
| `betting_destination` | `rejected` | destino é operadora de apostas |
| `limit_exceeded` | `rejected` | o que já saiu no período + este Pix > limite. O noturno (20h–6h) só vale entre pessoas físicas distintas; nos outros casos vale o diurno |
| `repeat_after_fraud_rejection` | `rejected` | o mesmo destino (conta ou CPF/CNPJ) já foi rejeitado por suspeita para este cliente em 24h |
| `destination_account_blocked` | `rejected` | destino nosso com bloqueio em vigor |
| `dict_fraud_marker` | `rejected` | marcação de laranja/golpista no DICT em 12 meses **e** um reforço: conta destino < 90 dias, ≥ 2 pagadores novos em 7 dias ou rejeição por suspeita com outro cliente |
| `dict_marker` | piso 2FA | qualquer marcação válida (5 anos) que não virou rejeição |
| `new_device_limit` | piso 2FA | aparelho não cadastrado e Pix > R$ 200, ou > R$ 1.000 no dia somando todos os não cadastrados (IN BCB 491) |
| `new_device_structuring` | piso 2FA | aparelho não cadastrado, Pix de R$ 180–200 e outro igual em 24h |
| `dict_unavailable` | piso 2FA | destino de outro banco, sem DICT recente e nunca pago antes |

As que não dependem do DICT rodam antes da consulta: se uma delas rejeita,
o DICT nem é chamado. Aparelho **cadastrado** = Pix aprovado nesta conta em
≥ 3 dias distintos, o primeiro há ≥ 7 dias, usado nos últimos 12 meses.

### Score

Cada sinal soma pontos na escala de log-odds (**+10 pontos = chance de
fraude 2× maior**), com teto por família, mitigantes (até −40) e
assinaturas que dão bônus quando o padrão inteiro de um golpe aparece
(`scam_drain_pattern`, `safe_account_pattern`, `refund_to_third_party`,
`scam_ladder`, `takeover_cashout`, `night_coercion`, `fresh_mule`,
`mule_cashout`).

```
P = 1 / (1 + 10000 · 2^(−pontos/10))       prior: 1 fraude a cada 10.000 Pix
ρ = média do ρ das famílias, ponderada pelos pontos
```

### Política (teoria de custos)

| Situação | Decisão |
|---|---|
| P ≥ 50% | `rejected` (risco claro) |
| 10% ≤ P < 50% e ρ < 0,5 | `rejected` (fundada suspeita de golpe ou laranja) |
| 10% ≤ P < 50% e ρ ≥ 0,5 | `two_factor_required` (ameaça de identidade: o 2FA resolve) |
| P < 10% e P × valor × ρ > R$ 3 | `two_factor_required` (a fraude que o 2FA evita vale mais que o atrito) |
| senão | `approved` |

O piso das regras duras vem por cima: nenhuma camada desce a severidade.
Os parâmetros (R$ 3 de atrito do 2FA, cortes de 10% e 50%, prior, pesos)
estão em `src/engine/params.py`.

### Resposta: pública e interna

- **Pública** (`metadata`): `reasons` (regras duras e os 3 sinais de maior
  peso, com mensagens qualitativas), `alert` (só no 2FA, a partir do sinal
  mais forte), `hold_recommended` (2FA de golpe ou laranja: em produção vira
  retenção pelo temporizador) e `latency_ms`. Motivos sensíveis a PLD
  (laranja no pagador, fracionamento) saem como um único `risk_policy`: a lei
  proíbe avisar o cliente de suspeita de lavagem.
- **Interna** (`transaction_analysis.decision`, nunca na resposta): todos os
  sinais com pontos, P, ρ, pontos por família, regra da política, ameaça
  (`identidade`, `golpe`, `laranja`), `situation_type` para a notificação
  de infração, `basis` (evidência própria ou marcação de terceiro),
  `pld_alert` e `sanctions_freeze`. Os motivos ficam em `analysis_reason`
  com os pontos de cada um.

### Liberação manual

Pix barrado por suspeita, com liberação aberta do mesmo pagador e destino,
`max_amount` ≥ valor e validade ≥ data do Pix → `approved` (uso único). A
liberação desfaz a suspeita, não a obrigação: não libera limite, marcação
de fraude no DICT, sanções, apostas, destino bloqueado, regras do aparelho
não cadastrado nem `engine_error`.

### Recusas operacionais (antes do motor)

Não são antifraude: é o Pix que não tem como acontecer do jeito que veio.
Por isso não passam pelo motor nem contam como "Pix rejeitado" no resumo
diário.

| Regra | Lógica |
|---|---|
| `unknown_account` | agência + conta do pagador não existem no nosso banco |
| `account_owner_mismatch` | o CPF/CNPJ do pagador não é o titular da conta |
| `unknown_destination_account` | destino com o nosso ISPB que não existe |
| `destination_owner_mismatch` | destino nosso, mas com outro titular |
| `account_blocked` | conta pagadora com bloqueio em vigor |
| `insufficient_balance` | saldo < valor |

Se o motor quebrar, o Pix não é aprovado às cegas: sai
`two_factor_required` com o motivo `engine_error`.

**DICT.** Consultado a cada Pix (depois das regras duras), com timeout de
0,5 s. Se não responder, vale a resposta da última análise com o mesmo
destino (mesma conta **ou** mesmo CPF/CNPJ). Fallback com mais de 24h
continua valendo pelas marcações, mas conta como "sem DICT recente". A
análise só guarda em `dict_response` o que o DICT respondeu **naquela**
consulta — o fallback nunca encadeia outro fallback.

---

## Como rodar e testar

Precisa de **Docker** e, para os testes, **Python 3.11+**.

```bash
docker compose up
```

Sobe três serviços: `api` (porta 3000), `db` (PostgreSQL, 5432, já com os
dados de exemplo) e `mock` (o DICT, 1080). Espere o `api` ficar `healthy`.
Mudou o `database/*.sql`? O banco só lê esses arquivos quando nasce:
`docker compose rm -sfv db && docker compose up --build`.

### Mandando um Pix

Toda rota de Pix exige o header `INTERNAL-TOKEN` (padrão do Base Service).

```bash
curl -X POST http://localhost:3000/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "pix-000123",
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {
      "branch": "0001", "account_number": "88213",
      "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": { "document_number": "123.456.789-09" }
    },
    "destination_account": {
      "participant": "60701190", "branch": "3675", "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": { "document_number": "987.654.321-00" }
    },
    "source": {
      "device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
      "geolocation": { "latitude": -23.56, "longitude": -46.65 }
    }
  }'
```

```json
{
  "key": "84d79188-97f8-41dc-b4bc-649656b46bfa",
  "status": "two_factor_required",
  "metadata": {
    "reasons": [
      {"code": "new_destination_account", "message": "A conta de destino foi aberta recentemente."},
      {"code": "amount_above_profile", "message": "Valor acima do habitual da conta."},
      {"code": "first_payment_to_destination", "message": "Primeiro Pix para este destino."}
    ],
    "alert": "Você nunca pagou esta conta e ela tem sinais de risco. Se alguém pediu este Pix por telefone ou mensagem, desligue e fale com o banco.",
    "hold_recommended": true,
    "latency_ms": 85
  }
}
```

R$ 1.500 às 22h para uma conta de 7 dias que a Maria nunca pagou, 4,7× o
habitual dela: 78 pontos, P ≈ 2,2%, ρ ≈ 0,25 → P × V × ρ ≈ R$ 8 > R$ 3 →
2FA com alerta e retenção recomendada.

`201` na primeira vez; o mesmo `id` de novo devolve `200` com a mesma
análise, sem analisar nem debitar outra vez.

```bash
curl http://localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

O GET devolve a mesma camada pública do POST e o `payload` que chegou.

### Liberando um Pix barrado

O cliente reclama (fora da API) e um operador libera **aquele** Pix: mesmo
pagador, mesmo destino, até `max_amount`, até `expires_at` (comparado com o
`transaction_date` do Pix; sem ele, vale 1h a partir de agora). Uso único.

```bash
curl -X POST http://localhost:3000/manual_release   -H "INTERNAL-TOKEN: default_token"   -H "Content-Type: application/json"   -d '{
    "source_account": { "branch": "0001", "account_number": "88213" },
    "destination_account": { "participant": "60701190", "branch": "3675", "account_number": "10442" },
    "max_amount": 150000,
    "expires_at": "2026-10-17T23:59:00-03:00",
    "operator": "ana.risco",
    "reason": "Cliente confirmou por telefone"
  }'
```

`GET /manual_release/{key}` mostra se já foi usada, por qual Pix e o que o
motor tinha decidido sem ela (`overridden_status`, `overridden_reasons`).

### Dados de exemplo (seed, dados falsos)

| Conta (ag. 0001) | Titular | Aparelho cadastrado | Para testar |
|---|---|---|---|
| `88213` | Maria, 123.456.789-09 | `dvc-9f2c71a8` | a pagadora do enunciado; limite noturno R$ 2.000 |
| `10001` | João, 529.982.247-25 | `dvc-joao-1` | cliente comum |
| `66666` | Lucas, 390.533.447-05 | `dvc-lucas-1` | cara de laranja: conta de 12 dias, entra e sai o tempo todo |
| `20002` | Padaria, 11.222.333/0001-81 | `dvc-padaria-1` | PJ que recebe muitos Pix pequenos |
| `30003` | Carlos, 111.444.777-35 | `dvc-carlos-1` | conta bloqueada → `account_blocked` |

Outro `device_id` vale como aparelho não cadastrado (acima de R$ 200 → 2FA).

Listas restritivas: CNPJ `11.444.777/0001-61` é operadora de apostas
(`betting_destination`); CPF `191.191.191-00` está na lista do CSNU
(`sanctioned_party`).

No mock do DICT (`mock/dict-expectations.json`):

| Destino (ISPB / ag. / conta) | Marcação | Resultado |
|---|---|---|
| `60746948` / `0001` / `990666` | laranja (conta) e golpista (dono), recentes | `dict_fraud_marker` se a conta destino tem < 90 dias; senão piso 2FA |
| `00360305` / `0001` / `990701` | laranja há 8 meses | idem |
| `00360305` / `0001` / `990702` | golpista há 2 anos | piso 2FA (`dict_marker`) |
| `00360305` / `0001` / `990703` | identidade falsa no CPF | piso 2FA: o CPF é da vítima |
| `00360305` / `0001` / `990704` | `OTHER` recente | só pesa no score |
| qualquer outra | sem marcação | — |

### Testes

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

- `tests/unit/` — o motor e as contas de período, sem Docker. Inclui os 46
  cenários do `4.2` (legítimos difíceis L1–L19 e golpes G1–G21) em
  `tests/unit/engine/test_scenarios.py`.
- `tests/integration/` — a API de pé, por HTTP. Como não existe rota de
  cadastro (onboarding fora do escopo), cada teste cria suas contas direto
  no banco (`tests/utils/scenario.py`), com aparelho próprio já cadastrado,
  e ensina ao mock a resposta do DICT só para elas. Ninguém apaga o banco.

---

## Modelo de dados

`database/database.sql`. Valores em centavos, datas com fuso, documento só
com dígitos (11 = PF, 14 = PJ).

| Tabela | O que guarda |
|---|---|
| `customer` | documento, nome, nascimento/fundação |
| `account` | agência, conta, abertura, saldo, limite diurno e noturno |
| `account_block` | bloqueios da conta (`ended_at` vazio = bloqueada agora) |
| `restricted_party` | CPF/CNPJ em lista restritiva: `csnu`, `bets`, `court_order` |
| `account_baseline` | o resumo diário: médias e p90 de entrada e saída, Pix por dia (entrada e saída), dias de histórico, fração noturna das saídas, bloqueios e Pix rejeitados por suspeita (como pagador e como destino). Uma linha por conta por dia, criada no primeiro Pix do dia |
| `pix_transaction` | tudo que chegou no POST, com o destino em colunas indexadas e o `payload` original |
| `account_statement` | o extrato: só dinheiro que moveu (Pix aprovado ou histórico do seed) |
| `analysis_status` | `approved`, `two_factor_required`, `rejected` |
| `transaction_analysis` | a decisão: `key`, status, pontos (`score`), latência, features, resposta do DICT, camada interna (`decision`), `alert` e `hold_recommended` |
| `analysis_reason` | os motivos (código, mensagem e pontos); mais de um por Pix |
| `manual_release` | liberações manuais: pagador, destino, valor máximo, validade, operador e motivo; no uso, o Pix e a decisão que foi desfeita |

Nenhum score é salvo por conta: o que se salva é o resumo do histórico; o
resto (já pagou esse destino? aparelho cadastrado? outros clientes pagaram
esse destino?) é consultado direto no histórico, na hora.

## Códigos de erro

Mesmo formato do Base Service (`title`, `description`, `translation`, `code`).

| Código | Quando |
|---|---|
| `QIT000001` | o JSON está fora do formato (`src/schemas/post_pix_transaction.json`) |
| `QIT000002` | faltou o `INTERNAL-TOKEN`, ou ele está errado |
| `QIT000404` / `QIT000405` | rota inexistente / método não aceito |
| `QIT000500` | erro inesperado |
| `QIT001001` | `GET` de um Pix que nunca chegou |
| `QIT001002` | data com formato certo que não existe no calendário (422) |
| `QIT002001` | liberação manual para uma conta pagadora que não existe |
| `QIT002002` | `GET` de uma liberação manual que não existe |

Uma recusa do motor **não** é erro HTTP: é um `201` com `status: rejected`.

## As pastas

```
src/
  resources/     HTTP: confere o formato, chama o controller, responde
  controllers/   o fluxo do Pix, o resumo diário, o DICT e as features
  engine/        o motor: Features → EngineResult (puro, sem banco)
    params.py      todos os pesos, limiares e custos
    measures.py    medidas derivadas (p90 combinado, aparelho cadastrado, DICT...)
    hard_rules.py  regras duras
    signals/       sinais por família e assinaturas
    scoring.py     tetos, mitigantes, P e ρ
    policy.py      a política de custo
    response.py    camada pública × interna
  repositories/  as consultas ao banco
  models/        as tabelas
  connectors/    o DICT (MockServer)
  schemas/       o contrato de entrada (JSON Schema)
database/        schema e seed
mock/            as respostas padrão do DICT
docs/motor.md    o motor por dentro e como calibrar
tests/           unit (motor) e integration (API)
```
