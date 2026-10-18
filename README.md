# Pix Antifraude — Hacka QI

**Integrantes:** Bruno Guimarães Duarte, Ana

API que recebe um Pix enviado por um cliente nosso, decide se ele pode sair
e grava tudo que chegou. Feita a partir do Base Service do Bootcamp QI Tech:
Python + FastAPI, PostgreSQL e Docker, nas mesmas camadas
(resource → controller → repository).

Cada Pix sai com um de três status:

| Status | Quando | O que significa para o BC |
|---|---|---|
| `approved` | risco baixo para o valor | — |
| `two_factor_required` | há **suspeita**: vale confirmar com o cliente (e, no golpe, alertar e reter) | suspeita |
| `rejected` | **fundada suspeita** de fraude, ou uma obrigação legal | o BC manda rejeitar (Regulamento do Pix, art. 38, II) |

A ideia central: **uma transação sozinha diz pouco**. A API compara o Pix com
o que o pagador e o destino já fizeram antes, consulta o DICT e entrega isso
pronto a um motor de regras e pontos que é puro (sem banco, sem relógio),
auditável e reproduzível.

**Sumário:** [1. Rodar e testar](#1-como-rodar-e-testar) ·
[2. A API](#2-a-api) · [3. O que analisamos](#3-o-que-a-api-analisa-e-por-quê) ·
[4. O motor](#4-como-o-motor-decide) ·
[5. Dados de teste](#5-dados-de-teste) · [6. Limitações](#6-limitações) ·
[Dicionário do motor](docs/dicionario-motor.md)

---

## 1. Como rodar e testar

Precisa de **Docker** e, para os testes, **Python 3.11+**.

```bash
docker compose up
```

Sobe a `api` (porta 3000), o `db` (PostgreSQL, já com dados de exemplo) e o
`mock` do DICT (porta 1080). Com a API `healthy`:

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/unit/` roda sem Docker (só o motor); `tests/integration/` precisa do
`docker compose up`. Mudou um `database/*.sql`? O banco só lê esses arquivos
quando nasce: `docker compose rm -sfv db && docker compose up --build`.

---

## 2. A API

Toda rota (menos `/` e `/health_check`) exige o header `INTERNAL-TOKEN`
(padrão do Base Service; no compose, `default_token`).

| Rota | O que faz |
|---|---|
| `POST /pix/transaction` | analisa um Pix e responde a decisão. `201` na primeira vez; o mesmo `id` de novo devolve `200` com a análise gravada (idempotente: não analisa nem debita duas vezes) |
| `GET /pix/transaction/{id}` | a mesma resposta pública do POST e o `payload` que chegou |
| `POST /manual_release` | um operador libera um Pix que foi barrado (ver [2.3](#23-liberação-manual)) |
| `GET /manual_release/{key}` | a liberação: se já foi usada, por qual Pix e o que o motor tinha decidido sem ela |
| `GET /health_check` | a API está de pé (`204`) |

### 2.1 O que acontece num POST

O controller cuida de tudo que é banco e HTTP; o motor (`src/engine/`) só
recebe as features e devolve a decisão.

```
POST /pix/transaction
 CONTROLLER
  1. id já visto?              → devolve a análise gravada
  2. trava as contas           → saldo e limite lidos sem corrida
  3. grava o Pix               → tudo que chega fica no banco, inclusive o rejeitado
  4. recusas operacionais      → conta inexistente, titular errado, bloqueada, sem saldo
  5. resumo diário             → o "habitual" da conta (30 dias), calculado 1x por dia
  6. features                  → pagador, destino, relação, aparelho, ritmo
 MOTOR
  7. regras duras sem DICT     → limite, sanções, apostas, insistência... rejeitou? para aqui
  8. DICT (ou fallback)        → regras duras do DICT
  9. sinais → pontos → P e ρ   → política de custo → decisão
 CONTROLLER
 10. liberação manual          → barrado por suspeita e liberado? aprova
 11. grava a análise           → status, motivos com pontos, features, DICT, camada interna
 12. approved?                 → debita, credita (se o destino é nosso) e lança no extrato
```

- **DICT depois das regras duras:** é a única consulta externa e a mais lenta.
  Se o limite já rejeita, não há por que esperar o BC.
- **DICT fora do ar:** timeout de 0,5 s. Sem resposta, vale a da última
  análise com o mesmo destino (conta **ou** CPF/CNPJ). Fallback com mais de
  24h ou inexistente = "sem DICT": para destino de outro banco nunca pago,
  isso vira piso de `two_factor_required`. O motor nunca trava esperando.
- **Motor quebrou?** O Pix não é aprovado às cegas: `two_factor_required`
  com o motivo `engine_error`.

### 2.2 A resposta

```json
{
  "key": "84d79188-97f8-41dc-b4bc-649656b46bfa",
  "status": "two_factor_required",
  "metadata": {
    "reasons": [
      {"code": "new_destination_account", "message": "A conta de destino foi aberta recentemente."},
      {"code": "first_payment_to_destination", "message": "Primeiro Pix para este destino."}
    ],
    "alert": "Você nunca pagou esta conta e ela tem sinais de risco. Se alguém pediu este Pix por telefone ou mensagem, desligue e fale com o banco.",
    "hold_recommended": true,
    "latency_ms": 85
  }
}
```

A resposta tem duas camadas:

- **Pública** (`metadata`, também no GET): `reasons` (as regras duras e os 3
  sinais de maior peso, com mensagens qualitativas: "aberta recentemente", não
  "há 3 dias"), `alert` (só no 2FA, montado a partir do sinal mais forte),
  `hold_recommended` (2FA de golpe: em produção vira retenção pelo
  temporizador do BC) e `latency_ms`. Motivos de lavagem (laranja no pagador,
  fracionamento) saem como um único `risk_policy`: a lei proíbe avisar o
  cliente de suspeita de lavagem (Lei 9.613, art. 11).
- **Interna** (`transaction_analysis.decision`, nunca na resposta): todos os
  sinais com pontos, P, ρ, a linha da política, a ameaça (`identidade`,
  `golpe`, `laranja`), `pld_alert`, `sanctions_freeze` e a base da decisão
  (evidência própria ou marcação de outro banco).

Exemplo de chamada:

```bash
curl -X POST http://localhost:3000/pix/transaction \
  -H "INTERNAL-TOKEN: default_token" -H "Content-Type: application/json" \
  -d '{
    "id": "pix-000123", "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": { "branch": "0001", "account_number": "88213",
      "opening_date": "2025-03-02T10:00:00-03:00",
      "owner": { "document_number": "123.456.789-09" } },
    "destination_account": { "participant": "60701190", "branch": "3675", "account_number": "10442",
      "opening_date": "2026-10-10T09:00:00-03:00",
      "owner": { "document_number": "987.654.321-00" } },
    "source": { "device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
      "geolocation": { "latitude": -23.56, "longitude": -46.65 } }
  }'
```

### 2.3 Liberação manual

O cliente reclama de um Pix barrado (fora da API) e um operador libera
**aquele** Pix: mesmo pagador, mesmo destino, até `max_amount`, até
`expires_at` (1h por padrão), uso único. O controller aplica a liberação
**depois** do motor, que continua puro, e grava os motivos que foram
desfeitos.

```bash
curl -X POST http://localhost:3000/manual_release \
  -H "INTERNAL-TOKEN: default_token" -H "Content-Type: application/json" \
  -d '{ "source_account": { "branch": "0001", "account_number": "88213" },
        "destination_account": { "participant": "60701190", "branch": "3675", "account_number": "10442" },
        "max_amount": 150000, "expires_at": "2026-10-17T23:59:00-03:00",
        "operator": "ana.risco", "reason": "Cliente confirmou por telefone" }'
```

A liberação desfaz a **suspeita**, não a **obrigação**. Não são liberáveis:
limite (`limit_exceeded`), marcação de fraude no DICT (`dict_fraud_marker`),
sanções, apostas, destino bloqueado, as regras do aparelho não cadastrado (o
caminho é cadastrar o aparelho) e `engine_error`.

### 2.4 Códigos

**Recusas operacionais** (antes do motor; não são antifraude, é o Pix que não
tem como acontecer, e não contam como "Pix rejeitado" no histórico):
`unknown_account`, `account_owner_mismatch`, `unknown_destination_account`,
`destination_owner_mismatch`, `account_blocked`, `insufficient_balance`.

**Recusas do motor**: as regras duras (seção 4.2) e os sinais (seção 4.3). A
lista completa, com condição e motivo, está no
[dicionário](docs/dicionario-motor.md).

**Erros HTTP** (formato do Base Service: `title`, `description`,
`translation`, `code`). Uma recusa **não** é erro: é `201` com
`status: rejected`.

| Código | Quando |
|---|---|
| `QIT000001` | JSON fora do contrato (`src/schemas/post_pix_transaction.json`) |
| `QIT000002` | `INTERNAL-TOKEN` ausente ou errado |
| `QIT000404` / `QIT000405` | rota inexistente / método não aceito |
| `QIT000500` | erro inesperado |
| `QIT001001` | `GET` de um Pix que nunca chegou |
| `QIT001002` | data bem formatada que não existe no calendário (422) |
| `QIT002001` | liberação manual para conta pagadora inexistente |
| `QIT002002` | `GET` de uma liberação que não existe |

---

## 3. O que a API analisa e por quê

O BC não dá uma fórmula, mas diz **o que** o banco tem que olhar:

- **Regulamento do Pix, art. 89, § 1º:** o banco precisa de um mecanismo que
  use o **DICT** e identifique transação "atípica ou não compatível com o
  perfil" do cliente.
- **Art. 39-B** (bloqueio cautelar): lista fatores como **idade da conta**,
  **horário**, **perfil** do cliente e **recorrência entre os dois usuários**.
- **IN BCB 491/2024:** aparelho não cadastrado tem teto de R$ 200 por Pix e
  R$ 1.000 por dia.
- **IN BCB 512** e **Res. 142:** limites diurno e noturno; o limite pode ser
  menor sem geolocalização.
- **Carta Circular 4.001:** indícios de lavagem (movimentação incompatível,
  conta de passagem, conta dormente que volta a movimentar, vários pagadores
  para a mesma conta).
- **Art. 37-A:** é **proibido** limitar a quantidade de Pix. Por isso
  velocidade só entra como pontos, nunca como teto.

Com isso, o que a API monta para o motor (`Features`, em
`src/engine/features.py`):

| Bloco | O que olhamos | Por quê | Base |
|---|---|---|---|
| **Transação** | valor, hora local, período (diurno 6h–20h, noturno 20h–6h), valor ÷ saldo, valor ÷ p90 de saída | "zerar a conta" e valor fora do habitual são a cara da falsa central e da invasão | perfil e horário (art. 39-B); noturno (IN 512) |
| **Pagador** | idade da conta, saldo, limites, bloqueios, resumo de 30 dias (médias, p90, Pix por dia, fração noturna), fluxo de 24h | define o "habitual" e mostra se o pagador está repassando dinheiro de outros | perfil (art. 89); Carta Circular 4.001 |
| **Destino** | idade da conta, DICT, quantos clientes nossos pagaram ele pela 1ª vez em 7 dias (fan-in), rejeições por suspeita com outros clientes; se for nosso, o perfil completo | a laranja é o elo que se repete entre vítimas | idade da conta (art. 39-B); DICT (art. 89) |
| **Relação** | já pagou esse destino? quanto, quantas vezes, há quanto tempo; valores crescendo; o destino já pagou o pagador; mesmo titular | quase toda fraude vai para destino novo; recorrência alivia | recorrência (art. 39-B) |
| **Aparelho** | aparelho cadastrado (Pix aprovado em ≥ 3 dias, o 1º há ≥ 7), IP, canal, outras contas no mesmo aparelho, distância e velocidade desde o último Pix | invasão de conta quase sempre usa aparelho novo | IN 491; IN 512, § 15 |
| **Ritmo** | tentativas em 24h, destinos novos no período, tentativas depois de um 2FA ou rejeição | o golpista tira o máximo antes de ser percebido | só como sinal (art. 37-A) |
| **Listas** | CPF/CNPJ na lista do CSNU (ONU), operadoras de apostas | obrigação legal | art. 38, V; art. 32, XI |

**O que não usamos, de propósito:** idade, renda e profissão do cliente. Renda
e profissão são autodeclaradas e sem fonte confiável; idade seria
discriminação (LGPD; Estatuto da Pessoa Idosa). O "normal" de cada conta vem
só do histórico dela. **O que não temos** (e seria a primeira evolução):
ligação ativa durante o Pix, acesso remoto, SIM swap, biometria
comportamental, idade da chave Pix.

Todas as features ficam gravadas em `transaction_analysis.features`: toda
decisão pode ser refeita com os mesmos dados.

---

## 4. Como o motor decide

### 4.1 Visão geral

Toda fraude num Pix que sai de um cliente nosso responde "não" a pelo menos
uma de quatro perguntas, e a resposta muda o que funciona contra ela:

| Pergunta | Ameaça | Família de sinais | O 2FA resolve? (ρ) |
|---|---|---|---|
| Quem opera é o dono? | invasão de conta | `identity` | sim (0,9) |
| O dono age por vontade própria? | golpe, coação | `magnitude`, `velocity`, `relationship`, `context` | pouco (0,3–0,4): a vítima confirma o próprio golpe |
| O destino é confiável? | laranja no destino | `destination` | não (0,1) |
| O pagador repassa dinheiro de outros? | laranja no pagador | `payer_mule` | não (0,1) |

O motor roda em etapas, e **cada etapa só pode subir a severidade**:

```
1. Regras duras     obrigações legais e fatos sem dúvida      → rejected ou piso de 2FA
2. Medidas          números derivados (p90 combinado, fatia do saldo, ...)
3. Sinais           cada um soma pontos na sua família         → teto por família
4. Assinaturas      bônus quando o padrão inteiro de um golpe aparece
5. Score            pontos → probabilidade P e eficácia do 2FA ρ
6. Política         P, ρ e o valor → approved / two_factor_required / rejected
```

### 4.2 Regras duras

Não passam pelo score. As principais:

| Regra | Decisão | Por quê |
|---|---|---|
| `sanctioned_party`, `betting_destination` | `rejected` | pagador/destino sancionado pela ONU; Pix para apostas. Obrigação legal |
| `limit_exceeded` | `rejected` | passou do limite do período. À noite vale sempre o limite noturno |
| `repeat_after_fraud_rejection` | `rejected` | o mesmo destino já foi rejeitado por suspeita para este cliente em 24h ("tenta um valor menor" é roteiro de golpe) |
| `dict_fraud_marker` | `rejected` | marcação de laranja/golpista no DICT em 12 meses **e** um reforço (conta destino < 90 dias, vários pagadores novos ou rejeição com outro cliente) |
| `dict_marker` | piso 2FA | marcação válida que não chegou a rejeitar |
| `new_device_limit` | piso 2FA | aparelho não cadastrado acima de R$ 200 no Pix ou R$ 1.000 no dia (IN 491) |
| `dict_unavailable` | piso 2FA | destino de outro banco, sem DICT e nunca pago antes |

### 4.3 Pontos: a teoria dos pesos

Cada sinal soma **pontos em escala de log-odds**: **+10 pontos = chance de
fraude 2× maior**. Então +20 = 4×, +30 = 8×, +40 = 16×.

```
pontos de um sinal = 10 · log2(LR)       LR = quantas vezes o sinal é mais comum em fraude do que em Pix legítimo
P = 1 / (1 + 10.000 · 2^(−pontos/10))     prior: 1 fraude a cada 10.000 Pix
```

| Pontos | 0 | 40 | 60 | 80 | 100 | 120 | 140 |
|---|---|---|---|---|---|---|---|
| P | 0,01% | 0,16% | 0,64% | 2,5% | 9,3% | 29% | 62% |

É um *scorecard* (um naive Bayes montado por especialista), o caminho usual
para quem começa sem dados rotulados. Três correções para o que ele erra:

- **Teto por família:** sinais correlacionados (valor acima do habitual e
  fatia do saldo medem quase a mesma coisa) contariam em dobro. Dentro de
  cada família os pontos somam até um teto.
- **Assinaturas:** tratar sinais como independentes subestima combinações
  raras. Quando o padrão inteiro de um golpe aparece (ex.: `scam_drain_pattern`
  = primeiro Pix + esvazia a conta + destino novo), entra um bônus.
- **Mitigantes:** destino recorrente, relação de mão dupla e conta própria
  antiga tiram pontos (até −40), mas nunca aliviam uma regra dura.

**ρ do Pix** = média do ρ das famílias, ponderada pelos pontos de cada uma:
diz se a evidência é mais de "não é o dono" (2FA resolve) ou de "golpe /
laranja" (2FA não resolve).

**Como os valores foram quantificados.** Os pesos atuais são **premissas de
especialista**, não foram ajustados com dados reais (não temos rótulos de
fraude). O que usamos:

1. **Pesquisa externa** (relatórios de mercado e regulação, compilados no
   repositório de contexto) para ordenar os sinais e ancorar os LR quando há
   número público. Exemplos: pagamento a beneficiário novo concentra 67% da
   fraude em 7% dos pagamentos (NICE, LR ≈ 9,6); aparelho ou login novo é 16×
   mais associado a fraude não autorizada (FICO); 47% das contas laranja
   encerradas no Reino Unido tinham < 1 ano (FCA).
2. **Pontos abaixo dos números de fornecedor**, porque as nossas medidas são
   mais grosseiras: "primeira vez para o destino" vale +15 (LR 2,8), não
   os ~33 que o LR da NICE daria.
3. **Indícios do BC e da Carta Circular 4.001** para os sinais sem número
   público (passagem, conta dormente, incompatibilidade de volume).
4. **Prior** de 1:10.000 a partir dos dados abertos do MED (4 a 9
   contestações aceitas por 100 mil Pix, que subestimam a fraude real).
5. **Conferência em 46 cenários** escritos por nós (19 legítimos difíceis e
   27 golpes, em `tests/unit/engine/test_scenarios.py`). Eles conferem se as
   decisões fazem sentido; os pesos **não** foram mexidos para acertar os
   cenários, senão o motor estaria ajustado aos nossos próprios exemplos.

Todos os pesos, tetos, limiares e custos ficam num arquivo só,
`src/engine/params.py`, e se recalibram sem mexer no motor. Em produção, cada
fraude confirmada (MED) e cada falso positivo reclamado recalculam o LR de
cada sinal.

### 4.4 Custos: a política

Para um Pix com probabilidade de fraude P e valor V (em reais):

```
custo(aprovar)  = P · V                        fraude que passa
custo(2FA)      = c₂ + P · V · (1 − ρ)         atrito + fraude que o 2FA não barra
custo(rejeitar) = (1 − P) · (c_r + α · V)      cliente bom barrado
```

Com c₂ = R$ 3 (atrito de pedir confirmação a um cliente bom), c_r = R$ 20 e
α = 10% (SAC, retrabalho, risco de perder o cliente), a conta vira cinco
regras:

| Situação | Decisão |
|---|---|
| P ≥ 50% | `rejected`: mais provável fraude do que não |
| 10% ≤ P < 50% e ρ < 0,5 | `rejected`: fundada suspeita de golpe ou laranja (o 2FA não resolve) |
| 10% ≤ P < 50% e ρ ≥ 0,5 | `two_factor_required`: a ameaça é de identidade, e o 2FA barra quem não é o dono |
| P < 10% e **P × V × ρ > R$ 3** | `two_factor_required`: a fraude que o 2FA evita vale mais que o atrito |
| senão | `approved` |

- Abaixo de 10%, rejeitar nunca é a ação mais barata; a comparação é
  aprovar × 2FA, e o 2FA ganha quando `P·V·ρ > c₂`. Por isso Pix grande pede
  2FA com P bem menor que Pix pequeno.
- O corte único de 10% é **escolha de compliance**: pela conta exata, um Pix
  pequeno para laranja ficaria em 2FA; mas pagar laranja é fundada suspeita,
  e a norma manda rejeitar qualquer que seja o valor.
- c₂ foi escolhido para a taxa de 2FA em legítimos ficar em 3–5%, o orçamento
  usual de desafio no mercado.

### 4.5 Exemplos

Rodados no motor real (cenários dos testes unitários):

| Cenário | Pontos | P | ρ | Decisão |
|---|---|---|---|---|
| **Falsa central:** R$ 8.000, 95% do saldo, destino aberto há 10 dias | 105 | 12,6% | 0,26 | `rejected`: magnitude 40 (teto) + destino novo 30 + primeira vez 15 + `scam_drain_pattern` 20; P ≥ 10% com ρ baixo |
| **A mesma falsa central, destino antigo e limpo** | 55 | 0,45% | 0,37 | `two_factor_required` com alerta e retenção: P·V·ρ ≈ R$ 13 > R$ 3 |
| **Laranja externa:** R$ 200 para conta de 3 dias que 4 outros clientes pagaram | 110 | 17% | 0,13 | `rejected`: destino 65 + `fresh_mule` 30 + primeira vez 15 |
| **Presente de R$ 50** para amigo com conta nova que 2 clientes pagaram | 95 | 6,8% | 0,13 | `approved`: destino suspeito, mas P·V·ρ = R$ 0,44 |
| **Roubo de conta:** aparelho novo, R$ 5.000, destino novo | 87 | 4,0% | 0,64 | `two_factor_required`: piso `new_device_limit`; ameaça de identidade |
| **Carro:** R$ 60.000 para conta antiga, 40× o habitual | 55 | 0,45% | 0,37 | `two_factor_required`: P baixo, mas P·V·ρ ≈ R$ 100 |
| **Aluguel recorrente** de R$ 2.000 (83% do saldo) | −1 | 0,01% | — | `approved`: a recorrência (−20) compensa a fatia do saldo |

**Como o DICT entra:** duas vezes. Como **regra dura**, marcação recente de
laranja/golpista com reforço rejeita (R$ 100 para conta marcada há 8 meses e
aberta há 60 dias → `rejected`); sem reforço, a mesma marcação numa conta de 3
anos é piso de 2FA. E como **sinal** (`dict_history`, +5 a +40 conforme o tipo
e a idade da marcação), que soma com os outros sinais do destino.

O que **cada** sinal, regra, peso e custo significa, com a condição exata e o
porquê, está no **[dicionário do motor](docs/dicionario-motor.md)**.

---

## 5. Dados de teste

**Seed** (`database/seed.sql` e `mock/dict-expectations.json`): algumas
contas, aparelhos, listas restritivas e destinos marcados no DICT, só para
**testar à mão** com `curl`. Dados falsos.

| Conta (ag. 0001) | Titular | Para testar |
|---|---|---|
| `88213` | Maria, 123.456.789-09, aparelho `dvc-9f2c71a8` | a pagadora do enunciado |
| `10001` | João, 529.982.247-25, `dvc-joao-1` | cliente comum |
| `66666` | Lucas, 390.533.447-05, `dvc-lucas-1` | cara de laranja (conta de 12 dias, entra e sai) |
| `20002` | Padaria (PJ), 11.222.333/0001-81, `dvc-padaria-1` | PJ com muitos Pix pequenos |
| `30003` | Carlos, 111.444.777-35 | conta bloqueada |

Outro `device_id` = aparelho não cadastrado. CNPJ `11.444.777/0001-61` é
operadora de apostas; CPF `191.191.191-00` está na lista do CSNU. Destinos
marcados no mock do DICT: ISPB `60746948` ag. `0001` conta `990666`, e ISPB
`00360305` ag. `0001` contas `990701` a `990704` (um tipo de marcação cada).

**Os testes de verdade não dependem do seed:**

- **Unitários** (`tests/unit/`, sem Docker): o motor recebe `Features`
  montados em código (`features_factory.py`) e um DICT falso. Há testes das
  regras duras (no limiar e logo abaixo), de cada linha da política, do score
  (tetos, mitigantes, ρ), os 46 cenários e propriedades (nenhuma camada desce a
  severidade; nenhum motivo de PLD aparece na resposta pública).
- **Integração** (`tests/integration/`, com a API de pé): como não existe rota
  de cadastro (onboarding está fora do escopo), cada teste **cria as próprias
  contas direto no banco** (`tests/utils/scenario.py`), com número aleatório e
  histórico (extrato antigo, aparelho já cadastrado). Os testes não se
  esbarram e ninguém apaga o banco. O Pix testado entra pela API.
- **Mock do DICT:** cada teste ensina ao MockServer a resposta **só para as
  contas que criou** (`tests/utils/mock_generator.py`): sem marcação, com
  marcações de conta e de dono (tipo e data), erro 500, conexão derrubada e
  resposta lenta (para testar o timeout e o fallback). É isso que o mock
  precisa ter; o `dict-expectations.json` é só o padrão para os testes
  manuais.

---

## 6. Limitações

- **Pesos sem dados reais.** São premissas ancoradas em pesquisa e conferidas
  em cenários escritos por nós: o benchmark mostra coerência, não precisão no
  mundo real. A calibração de verdade exige rótulos (MED, reclamações).
- **Golpe autorizado contra destino limpo** (investimento, amor, falsa central
  para conta antiga) fica em 2FA ou passa: sem nada contra o destino, o motor
  não tem como saber. A defesa é o alerta, a retenção e o destino ficar
  marcado quando outras vítimas aparecerem.
- **Conta segura × portabilidade:** "mande tudo para uma conta nova no seu
  nome" e mudar de banco são idênticos nos dados. Os dois levam 2FA com
  alerta, nunca rejeição.
- **Laranja constante:** sem renda, a conta que recebe e repassa no mesmo
  ritmo desde que abriu não tem salto contra o próprio histórico. Ela leva 2FA,
  e só é rejeitada quando aparece outro sinal (fan-in, DICT, rejeição com
  outro cliente).
- **Racha e vaquinha** (recebe de vários e paga um) levam 2FA e alerta de PLD:
  é o preço de olhar a laranja no pagador.
- **Só três status.** O temporizador do BC (reter 30–60 min) não existe no
  contrato: vira `two_factor_required` com `hold_recommended`.
- **Sem retorno do 2FA.** Um Pix confirmado no 2FA não vira aprovado na API, e
  o aparelho só fica cadastrado por uso (3 dias), não pela confirmação.
- **Visão só da nossa base.** Fan-in e rejeições do destino contam só os
  nossos clientes; de outros bancos, só o que o DICT diz. O DICT do
  **pagador** não é consultado.
- **Fora do escopo:** Pix recebido (bloqueio cautelar na entrada), fila de
  PLD e comunicação ao COAF, notificação de infração no DICT, configuração por
  conta (noturno às 22h, destinatário cadastrado) e os sinais que o payload
  não traz (ligação ativa, acesso remoto, SIM swap).

---

## Pastas

```
src/
  resources/     HTTP: confere o formato, chama o controller, responde
  controllers/   o fluxo do Pix, o resumo diário, o DICT, as features, a liberação manual
  engine/        o motor: Features → EngineResult (puro, sem banco)
    params.py      todos os pesos, limiares e custos
    hard_rules.py  regras duras · measures.py medidas · signals/ sinais e assinaturas
    scoring.py     tetos, mitigantes, P e ρ · policy.py política · response.py camadas
  repositories/  consultas ao banco · models/ tabelas · connectors/ DICT
database/        schema e seed
mock/            respostas padrão do DICT
docs/            dicionario-motor.md (cada regra e sinal) e motor.md (contrato do motor)
tests/           unit (motor) e integration (API)
```

Valores sempre em centavos, datas com fuso, documento só com dígitos. Nenhum
score é salvo por conta: o que se salva é o resumo diário do histórico; o
resto é consultado na hora.
