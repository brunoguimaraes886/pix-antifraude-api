# Pix Antifraude — Hacka QI

**Integrantes:** Bruno Guimarães Duarte, Ana

API que recebe um Pix, decide se ele pode sair (`approved`,
`two_factor_required` ou `rejected`) e grava tudo que chegou. Feita a
partir do Base Service do Bootcamp QI Tech: Python + FastAPI, PostgreSQL,
Docker, com as mesmas camadas (resource → controller → repository).

> **Estado atual:** a estrutura está completa — contrato da API, banco,
> histórico, features, DICT com fallback e testes. O motor de decisão em
> uso é **provisório** (só os vetos abaixo); o motor definitivo entra em
> `src/engine/` sem mexer no resto. Veja [docs/motor.md](docs/motor.md).

---

## Como o motor de decisão funciona

Uma transação sozinha diz pouco. A API compara o Pix com o que o pagador e
o destino já fizeram antes, e entrega isso pronto ao motor:

```
POST /pix/transaction
  1. já recebido?             → devolve a análise gravada (idempotente)
  2. trava as contas          → saldo e limite lidos sem corrida
  3. grava o Pix              → tudo que chega fica no banco, inclusive o rejeitado
  4. recusas operacionais     → conta inexistente, bloqueada, sem saldo...
  5. resumo diário            → o "habitual" da conta (30 dias), 1x por dia
  6. DICT                     → marcações de fraude do destino (ou fallback)
  7. features → motor         → a decisão e os motivos
  8. grava a análise          → status, motivos, latência, features, DICT
  9. approved?                → debita, credita (se o destino é nosso) e lança no extrato
```

**Quem é analisado.** Só Pix que sai de um cliente nosso. Quem recebe pode
ser cliente nosso (mesmo ISPB, `88888888`) — aí o motor vê o perfil
completo dela — ou de outro banco — aí vê o que temos: DICT, idade da
conta (`opening_date` do payload) e tudo que já chegou aqui com ela como
destino.

**O que o motor recebe** (`Features`, em `src/engine/features.py`):

| Bloco | Conteúdo |
|---|---|
| Transação | valor; hora local; período diurno/noturno; valor ÷ saldo, ÷ renda, ÷ média e ÷ p90 de saída |
| Pagador | PF/PJ, idade, profissão, renda; idade da conta; saldo; limites; bloqueio em vigor; resumo diário; fluxo das últimas 24h e dos períodos atual e anterior |
| Destino | conta nossa ou externa; idade da conta; histórico de tudo que chegou para ela (pagadores distintos, aprovados, rejeitados); DICT; perfil completo se for nossa |
| Relação | o pagador já pagou esse destino? quanto, quantas vezes, em quantos dias |
| Aparelho | device e IP já usados; aparelhos em 30 dias; distância e tempo desde o último Pix com localização |
| Velocidade | tentativas em 1h, 24h e no período (2FA e rejeitado contam) |

Cada janela de fluxo traz entrada e saída, contrapartes **novas** (nunca
vistas antes) e **repetidas**, **taxa de passagem** (saída ÷ entrada) e
**razão de saída** (saída ÷ (saldo no início + entrada)). Os períodos
seguem o fuso da própria transação: diurno das 6h às 22h, noturno das 22h
às 6h.

Todas as features ficam gravadas em `transaction_analysis.features`: toda
decisão é auditável e reproduzível.

## Regras

### Recusas operacionais (antes do motor)

Não são antifraude: é o Pix que não tem como acontecer do jeito que veio.
Por isso não passam pelo motor nem contam como "Pix bloqueado" no resumo
diário.

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `unknown_account` | agência + conta do pagador não existem no nosso banco | — | onboarding está fora do escopo: sem cadastro não há perfil para analisar |
| `account_owner_mismatch` | o CPF/CNPJ do pagador não é o titular da conta | — | o pedido diz que A paga, mas a conta é de B |
| `unknown_destination_account` | destino com o nosso ISPB que não existe | ISPB `88888888` | o dinheiro não teria onde cair |
| `destination_owner_mismatch` | destino nosso, mas com outro titular | — | idem ao do pagador |
| `account_blocked` | conta pagadora com bloqueio em vigor (`ended_at` vazio ou futuro) | — | conta bloqueada não movimenta |
| `insufficient_balance` | saldo < valor | — | o saldo só muda com Pix aprovado; não pode ficar negativo |

### Motor provisório (`src/engine/rules_engine.py`)

| Regra | Lógica | Parâmetros | Por quê |
|---|---|---|---|
| `limit_exceeded` → `rejected` | saída do período atual + este Pix > limite do período | diurno 6h–22h: `daily_limit`; noturno 22h–6h: `nightly_limit` | limite é teto da conta: passou, bloqueia na hora. O limite é do **período**, não do Pix — o que já saiu soma |
| `dict_fraud_marker` → `rejected` | a conta ou o CPF/CNPJ de destino tem marcação de fraude no DICT (inclusive via fallback) | qualquer marcação | veto: marcação no BC é o sinal mais forte que existe; numa média ponderada ele seria diluído |
| `dict_unavailable` → `two_factor_required` | destino de **outro banco**, DICT sem resposta e sem consulta anterior | timeout de 1 s | sem nada sobre quem recebe, a dúvida vira fricção, não bloqueio. Conta nossa não entra: dela conhecemos tudo |

## Como as regras viram decisão

1. Recusas operacionais primeiro. Pagador desconhecido (ou de outro
   titular) para ali; as demais se somam (bloqueada **e** sem saldo são
   dois motivos).
2. Depois o motor: todas as regras rodam, e a decisão é a **mais severa**
   (`rejected` > `two_factor_required` > `approved`). Os motivos são todos
   os que dispararam.
3. `approved` sai sem motivos. `two_factor_required` não movimenta saldo
   nem extrato (não há retorno da confirmação), mas conta como tentativa.
4. Se o motor quebrar, o Pix não é aprovado às cegas: sai
   `two_factor_required` com o motivo `engine_error`.

**DICT.** Consultado a cada Pix, com timeout de 1 s. Se não responder, vale
a resposta da última análise com o mesmo destino (mesma conta **ou** mesmo
CPF/CNPJ). A análise só guarda em `dict_response` o que o DICT respondeu
**naquela** consulta — o fallback nunca encadeia outro fallback.

---

## Como rodar e testar

Precisa de **Docker** e, para os testes, **Python 3.11+**.

```bash
docker compose up
```

Sobe três serviços: `api` (porta 3000), `db` (PostgreSQL, 5432, já com os
dados de exemplo) e `mock` (o DICT, 1080). Espere o `api` ficar `healthy`.

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
{"key":"77fcdc12-45f1-40e0-a6bf-45d3bdc89ead","status":"approved","metadata":{"reasons":[],"latency_ms":30}}
```

`201` na primeira vez; o mesmo `id` de novo devolve `200` com a mesma
análise, sem analisar nem debitar outra vez.

```bash
curl http://localhost:3000/pix/transaction/pix-000123 -H "INTERNAL-TOKEN: default_token"
```

O GET devolve `key`, `status` e `metadata` com `reasons`, `latency_ms` e o
`payload` que chegou.

### Contas de exemplo (seed, dados falsos)

| Conta (ag. 0001) | Titular | Para testar |
|---|---|---|
| `88213` | Maria, 123.456.789-09 | a pagadora do enunciado; limite noturno R$ 2.000 (Pix de R$ 3.000 às 23h → `limit_exceeded`) |
| `10001` | João, 529.982.247-25 | cliente comum |
| `66666` | Lucas, 390.533.447-05 | cara de laranja: conta de 12 dias, entra e sai o tempo todo |
| `20002` | Padaria, 11.222.333/0001-81 | PJ que recebe muitos Pix pequenos |
| `30003` | Carlos, 111.444.777-35 | conta bloqueada → `account_blocked` |

No mock do DICT, o destino `60746948` / `0001` / `990666` tem marcação de
fraude (→ `dict_fraud_marker`); qualquer outra conta volta sem marcação.

### Testes

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

- `tests/unit/` — o motor e as contas de período, sem Docker.
- `tests/integration/` — a API de pé, por HTTP. Como não existe rota de
  cadastro (onboarding fora do escopo), cada teste cria suas contas direto
  no banco (`tests/utils/scenario.py`) com número aleatório e ensina ao
  mock a resposta do DICT só para elas. Ninguém apaga o banco.

---

## Modelo de dados

`database/database.sql`. Valores em centavos, datas com fuso, documento só
com dígitos (11 = PF, 14 = PJ).

| Tabela | O que guarda |
|---|---|
| `customer` | documento, nome, nascimento/fundação, profissão/setor, renda mensal |
| `account` | agência, conta, abertura, saldo, limite diurno e noturno |
| `account_block` | bloqueios da conta (`ended_at` vazio = bloqueada agora) |
| `account_baseline` | o resumo diário: médias e p90 de entrada e saída, Pix por dia (entrada e saída), dias de histórico, bloqueios e Pix rejeitados (como pagador e como destino). Uma linha por conta por dia, criada no primeiro Pix do dia |
| `pix_transaction` | tudo que chegou no POST, com o destino em colunas indexadas e o `payload` original |
| `account_statement` | o extrato: só dinheiro que moveu (Pix aprovado ou histórico do seed) |
| `analysis_status` | `approved`, `two_factor_required`, `rejected` |
| `transaction_analysis` | a decisão: `key`, status, score (opcional), latência, features, resposta do DICT |
| `analysis_reason` | os motivos (código + mensagem); mais de um por Pix |

Nenhum score é salvo por conta: o que se salva é o resumo do histórico; o
resto (já pagou esse destino? aparelho já usado?) é consultado direto no
histórico, na hora.

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

Uma recusa do motor **não** é erro HTTP: é um `201` com `status: rejected`.

## As pastas

```
src/
  resources/     HTTP: confere o formato, chama o controller, responde
  controllers/   o fluxo do Pix, o resumo diário, o DICT e as features
  engine/        o motor: Features → EngineResult (puro, sem banco)
  repositories/  as consultas ao banco
  models/        as tabelas
  connectors/    o DICT (MockServer)
  schemas/       o contrato de entrada (JSON Schema)
database/        schema e seed
mock/            as respostas padrão do DICT
docs/motor.md    como plugar o motor definitivo
tests/           unit (motor) e integration (API)
```
