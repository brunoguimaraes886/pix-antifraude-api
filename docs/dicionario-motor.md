# Dicionário do motor

> **Isto é um dicionário, não um texto para ler de ponta a ponta.** Cada
> regra, medida, sinal, peso e custo do motor aparece aqui com a condição
> exata, o valor e o porquê. A visão geral (etapas, teoria dos pesos e dos
> custos, exemplos) está no [README](../README.md#4-como-o-motor-decide).
> Todos os números moram em `src/engine/params.py`; se um valor mudar lá, ele
> deve mudar aqui.

**Convenções.** Valores em reais (no código, em centavos). "Pontos" estão na
escala de log-odds: +10 pontos = chance de fraude 2× maior, então
`pontos = 10 · log2(LR)`, com LR = quantas vezes o sinal é mais comum em
fraude do que em Pix legítimo. "Nosso" = conta com o nosso ISPB (`88888888`).
"Por suspeita" = rejeição do motor que não seja só por limite nem
operacional.

**Sumário:** [A. Escala](#a-escala-e-prior) · [B. Regras duras](#b-regras-duras) ·
[C. Medidas](#c-medidas) · [D. Famílias](#d-famílias-teto-e-ρ) ·
[E. Sinais](#e-sinais) · [F. Assinaturas](#f-assinaturas) ·
[G. Score](#g-score) · [H. Política e custos](#h-política-e-custos) ·
[I. Liberação manual](#i-liberação-manual) · [J. Resposta](#j-resposta)

---

## A. Escala e prior

| Parâmetro | Valor | Por quê |
|---|---|---|
| `PDO` | 10 | Pontos para dobrar a chance. Escala usual de scorecard; deixa os pesos legíveis (+20 = 4×) |
| `PRIOR_ODDS` | 1 : 10.000 | A chance de fraude antes de olhar qualquer sinal. Os dados abertos do MED dão 4 a 9 contestações aceitas por 100 mil Pix (≈ 1:11.000 a 1:25.000), o que subestima (nem toda vítima contesta; tentativa barrada não entra). Fica a ordem de grandeza. O prior não muda a ordem dos casos, só onde caem os cortes |

```
P = 1 / (1 + 10.000 · 2^(−pontos/10))
```

| Pontos | 0 | 25 | 40 | 50 | 60 | 80 | 100 | 101 | 120 | 133 | 140 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | 0,01% | 0,06% | 0,16% | 0,32% | 0,64% | 2,5% | 9,3% | **10%** | 29% | **50%** | 62% |

Os dois cortes da política: P = 10% ≈ 101 pontos; P = 50% ≈ 133 pontos.

---

## B. Regras duras

Não passam pelo score. Todas rodam e vale a mais severa. As que **rejeitam**
encerram; as de **piso** garantem no mínimo `two_factor_required`, e nenhuma
etapa depois desce abaixo disso. Rodam em duas fases: antes do DICT (se uma
rejeita, o DICT nem é consultado) e depois dele.

### B.1 Antes do DICT

| Código | Condição | Decisão | Por quê |
|---|---|---|---|
| `sanctioned_party` | pagador ou destino na lista do CSNU (`restricted_party.list = csnu`) | `rejected` | Obrigatório para o pagador (Regulamento, art. 38, V); para o destino, por inferência (Lei 13.810, art. 8º: vedado disponibilizar recursos a sancionado). Liga `sanctions_freeze` na análise interna |
| `betting_destination` | destino na lista de operadoras de apostas (`bets`) | `rejected` | Obrigatório: o PSP deve impedir Pix destinado a apostas de quota fixa (art. 32, XI; MP 1.394/2026). Só o lado do destino |
| `limit_exceeded` | o que já saiu no período + este Pix > limite do período | `rejected` | "Passou do limite → bloqueia na hora". À noite (20h–6h) vale **sempre** o limite noturno, para qualquer destino (PF, PJ ou conta própria): mais fechado que o mínimo do BC, que o exige entre pessoas físicas (Res. 142; IN 512), e fecha a "conta segura" à noite |
| `repeat_after_fraud_rejection` | este destino (conta **ou** CPF/CNPJ) já teve Pix deste cliente rejeitado por suspeita nas últimas 24h | `rejected` | O risco do destino não muda em horas, e "tente um valor menor" / "mande para esta outra conta" é roteiro de golpista. Rejeição só por limite não conta |
| `destination_account_blocked` | destino nosso com bloqueio em vigor | `rejected` | Conta bloqueada não recebe. É também como a marcação de um cliente nosso por fraude vira efeito (art. 89, § 2º) |
| `new_device_limit` | aparelho não cadastrado **e** (Pix > R$ 200 **ou** o que saiu hoje de aparelhos não cadastrados + este Pix > R$ 1.000) | piso 2FA | Regra do BC (IN 491/2024, art. 9º), somando **todos** os aparelhos não cadastrados da conta. O cadastro, pela norma, é confirmar a identidade (art. 4º): é o nosso 2FA |
| `new_device_structuring` | aparelho não cadastrado, R$ 180 ≤ Pix ≤ R$ 200 **e** outro Pix nessa faixa de aparelho não cadastrado em 24h, qualquer destino | piso 2FA | Fracionamento para escapar da regra acima, mesmo trocando de destino. Liga `pld_alert` |

### B.2 Depois do DICT

| Código | Condição | Decisão | Por quê |
|---|---|---|---|
| `dict_fraud_marker` | marcação `MULE_ACCOUNT` ou `SCAMMER_ACCOUNT` (conta ou dono) com ≤ 12 meses **e** um reforço: conta destino < 90 dias, `fan_in ≥ 2` ou destino já rejeitado por suspeita com outro cliente em 90 dias | `rejected` | Critério **nosso** e documentado de fundada suspeita sobre o destino (Res. 142, art. 2º-A deixa o critério para o banco). Marcação de outro banco, sozinha, não obriga a rejeitar; o reforço evita punir CPF com marcação antiga e conta legítima. Grava `basis = third_party_mark` |
| `dict_marker` | qualquer marcação `MULE_ACCOUNT`, `SCAMMER_ACCOUNT` ou `APPLICATION_FRAUD` com ≤ 5 anos que não virou rejeição | piso 2FA | Suspeita, não fundada suspeita. `APPLICATION_FRAUD` aponta a **vítima** de roubo de identidade (alguém abriu conta no CPF dela), por isso nunca rejeita sozinha |
| `dict_unavailable` | destino de outro banco, sem DICT recente e o pagador nunca pagou esse destino | piso 2FA | Sem nada do BC sobre quem recebe e sem relação prévia, a dúvida vira fricção, não bloqueio. Destino nosso não precisa: os dados dele estão no nosso banco |

**DICT recente** = respondeu agora, ou o fallback (última análise com o mesmo
destino, por conta ou CPF/CNPJ) tem no máximo 24h. Fallback mais velho ainda
conta pelas marcações (não se esquece uma marcação), mas não tira o Pix do
"sem DICT recente".

| Parâmetro | Valor | Por quê |
|---|---|---|
| `DICT_HARD_DAYS` | 365 | Marcação "recente": pode rejeitar e pesa cheio no score |
| `DICT_VALID_DAYS` | 1.825 (5 anos) | Prazo de vida da marcação no CPF/CNPJ (Res. 587/2026) |
| `DICT_STALE_HOURS` | 24 | Fallback mais velho que isso não representa o destino de hoje |
| `DICT_REINFORCEMENT_ACCOUNT_DAYS` | 90 | Conta destino nova reforça a marcação |
| `DICT_REINFORCEMENT_FAN_IN` | 2 | Dois ou mais clientes nossos começando a pagar o destino em 7 dias |
| `DICT_API_TIMEOUT` | 0,5 s | O BC mira p50 ≤ 0,9 s e p95 ≤ 1,5 s para o PSP pagador inteiro; o DICT não pode comer esse orçamento |

### B.3 Aparelho cadastrado

| Parâmetro | Valor | Por quê |
|---|---|---|
| `DEVICE_KNOWN_DAYS` | 3 dias distintos com Pix aprovado | Um Pix de R$ 5 hoje não "aquece" o aparelho: o golpista teria que operar três dias sem o cliente perceber |
| `DEVICE_KNOWN_MIN_AGE_DAYS` | 7 | O primeiro Pix aprovado tem que ter pelo menos uma semana |
| `DEVICE_EXPIRY_DAYS` | 365 | Sem uso há 12 meses, deixa de ser cadastrado (IN 491, art. 7º, VI) |
| `COLD_START_ACCOUNT_DAYS` | 7 | Conta de até 7 dias sem outro aparelho com Pix aprovado: o aparelho é o do onboarding, não "novo". Conta antiga que nunca fez Pix **tem** aparelho não cadastrado |
| `NEW_DEVICE_MAX_PIX`, `NEW_DEVICE_MAX_DAY` | R$ 200, R$ 1.000 | Valores da IN 491 |
| `NEAR_LIMIT_MIN` | R$ 180 | Faixa logo abaixo do teto onde o fracionamento acontece |

Tentativas com 2FA ou rejeitadas não contam para cadastrar o aparelho.

---

## C. Medidas

Números derivados do `Features`, calculados no motor (`measures.py`). Não
decidem nada sozinhos; os sinais leem deles.

| Medida | Definição | Por quê |
|---|---|---|
| `n_out` | Pix de saída na janela de 30 dias (`avg_daily_out_count × history_days`) | Quanto histórico próprio o cliente tem |
| `p90_blend` | `exp((n·ln p90_próprio + k·ln R$ 500) / (n + k))`, k = 10 | O "valor habitual". Credibilidade de Bühlmann: com pouco histórico o cliente herda um perfil padrão; com 10 Pix, metade do perfil já é dele. Média geométrica porque valores de Pix têm cauda longa |
| `amount_ratio` | valor ÷ `p90_blend` | Quantas vezes acima do habitual |
| `balance_share` | valor ÷ saldo | Quanto da conta o Pix leva |
| `daily_count_blend` | `(n·Pix por dia + k·1) / (n + k)` | O ritmo habitual, com o mesmo prior |
| `exit_ratio_with_pix` | (saída 24h + valor) ÷ (saldo no início das 24h + entrada 24h) | Quanto do que havia disponível já saiu, contando este Pix |
| `pass_through_with_pix` | (saída 24h + valor) ÷ entrada 24h | Taxa de passagem: conta que não acumula |
| `inflow_jump` | entrada 24h ÷ max(entrada dos 30 dias, R$ 500). **Só com 30 dias de histórico** | Quantos "meses de entrada" chegaram num dia. Salário dá ~1; laranja coletando vítimas dá 3, 10 ou mais. Comparar com a média **diária** não serviria (o dia do salário daria 30×). Sem 30 dias, o primeiro salário pareceria laranja |
| `first_payment` | nunca pagou o destino, ou o primeiro Pix aprovado para ele foi há < 24h | Quase toda fraude vai para destino novo |
| `escalating` | ≥ 2 Pix anteriores ao destino, relação < 180 dias e valor > o maior já pago | Golpes de investimento, amor e tarefas começam pequeno e crescem |
| `recurring` | ≥ 3 Pix anteriores, relação ≥ 30 dias, não escalando, valor ≤ 1,5 × a média já paga e conta destino ≥ 180 dias | Aluguel, família, contas: lista de confiança automática |
| `two_way` | o destino já pagou ≥ R$ 50 a esta conta, a primeira vez há ≥ 30 dias | Relação de mão dupla. Piso de valor e tempo para o golpista não ganhar o mitigante mandando R$ 1 |
| `new_payees_period` | destinos novos no período atual (+1 se este também é novo) | Vários estranhos no mesmo período |
| `fan_in` | **outros** clientes nossos que pagaram este destino (conta ou CPF/CNPJ) pela primeira vez nos últimos 7 dias | Várias vítimas pagando a mesma conta. Funciona até com destino de outro banco |
| `fan_in_factor` | 3 se o destino é PJ, senão 1 | Empresa recebe de muita gente: os limiares de fan-in ficam 3× maiores |
| `dormant` | 30 dias de histórico, ≤ 0,1 Pix por dia (entrada + saída) e conta ≥ 180 dias | Conta parada (Carta Circular 4.001, IV-e) |
| `speed_kmh` | distância do último Pix com localização ÷ tempo desde ele | Viagem impossível |
| `dict_markers` | lista (tipo, idade em dias) das marcações de conta e de dono. Sem data = recente | Leitura defensiva: formato que vem de fora não derruba a decisão |

| Parâmetro | Valor | Por quê |
|---|---|---|
| `K_PRIOR` | 10 | Peso do perfil padrão, em "Pix". Com 10 Pix próprios, metade do perfil é do cliente |
| `P90_PRIOR` | R$ 500 | Valor habitual de quem não tem histórico. Mais fechado no começo, abre conforme o histórico cresce. Premissa a calibrar pela taxa de 2FA em contas novas |
| `DAILY_COUNT_PRIOR` | 1 Pix por dia | Ritmo de quem não tem histórico |
| `INFLOW_JUMP_FLOOR` | R$ 500 | Piso do mês anterior, para uma conta que quase não recebe não gerar saltos enormes com qualquer entrada |
| `FULL_HISTORY_DAYS` | 30 | `inflow_jump` e dormência só com a janela inteira |

Todas as contagens de tentativas excluem as recusas operacionais (sem saldo,
conta inexistente): elas não dizem nada sobre fraude.

---

## D. Famílias: teto e ρ

Cada sinal pertence a uma família. Dentro da família os pontos positivos
somam **até o teto**, porque sinais da mesma família medem coisas
correlacionadas e, somados livremente, contariam em dobro. ρ é a **eficácia
do 2FA** contra a ameaça que a família representa: a fração dessa fraude que
o 2FA barraria.

O teto define até onde uma família consegue empurrar o Pix **sozinha**. A
coluna da direita mostra o efeito: com só aquela família no teto, a partir de
que valor a política pede 2FA (P·V·ρ > R$ 3).

| Família | Teto | ρ | Por que o ρ | Por que o teto | Sozinha no teto |
|---|---|---|---|---|---|
| `identity` | 50 | 0,9 | Na invasão, quem opera não é o dono e não passa na biometria | Contra identidade o 2FA resolve: não precisa chegar à rejeição, só ao 2FA | P 0,32% → 2FA a partir de ~R$ 1.050 |
| `magnitude` | 40 | 0,4 | Valor anômalo aparece na invasão (2FA resolve) e no golpe (não resolve) | Valor e fatia do saldo medem quase o mesmo: juntos não passam de 16× | P 0,16% → 2FA a partir de ~R$ 4.700 |
| `velocity` | 40 | 0,4 | Mesmo raciocínio de magnitude | Ritmo nunca é teto legal (art. 37-A), só evidência moderada | idem |
| `relationship` | 30 | 0,3 | Golpe autorizado: a vítima confirma | "Destino novo" é comum em legítimo: sozinho não pode pesar muito | P 0,08% → 2FA só acima de ~R$ 12.500 |
| `destination` | 80 | 0,1 | Confirmar quem paga não muda quem recebe | A maior: a laranja no destino é o elo que se repete entre vítimas e é fundada suspeita; precisa de espaço para, com mais um sinal, cruzar os 10% | P 2,5% → 2FA a partir de ~R$ 1.200; com primeira vez (+15) e `fresh_mule` (+30), rejeita |
| `payer_mule` | 60 | 0,1 | O dono da laranja confirma o próprio Pix | Lavagem tem muito falso positivo (racha, vaquinha): forte, mas abaixo do destino | P 0,64% → 2FA a partir de ~R$ 4.700 |
| `context` | 25 | 0,3 | Sinais de contexto acompanham golpe e coação | Sinais fracos e ambíguos (madrugada, sem GPS) | P 0,06%: sozinha quase nunca pede nada |
| `pattern` (assinaturas) | 40 | o de cada assinatura | Cada assinatura representa uma ameaça específica | Bônus de conjunção, não evidência nova: não pode dominar o score | — |

**Mitigantes** (pontos negativos) entram depois dos tetos, com piso total de
**−40** (`MITIGATION_FLOOR`): uma relação boa alivia, mas não apaga um destino
com cara de laranja. Mitigantes só aliviam o score, **nunca** uma regra dura.

---

## E. Sinais

Formato: condição → pontos → por quê. Os pontos são **premissas de
especialista**: ordenados e ancorados pela pesquisa externa quando há número
público, em geral **abaixo** dos números de fornecedor (as nossas medidas são
mais grosseiras), e conferidos nos 46 cenários de
`tests/unit/engine/test_scenarios.py` sem serem ajustados a eles.

### E.1 Identidade (`identity`) — quem opera é o dono?

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `new_device` | aparelho não cadastrado (B.3) | +25 | Na invasão o aparelho novo aparece quase sempre; aparelho ou login novo é 16× mais associado a fraude não autorizada do que a golpe (FICO). LR assumido ≈ 5,7 |
| `new_ip` | IP nunca usado **e** aparelho não cadastrado | +5 | IP de celular muda o tempo todo (CGNAT): sozinho não diz nada; só reforça o aparelho novo |
| `shared_device` | o aparelho mandou Pix de ≥ 3 **outras** contas nossas em 30 dias | +20 | Fazenda de laranjas ou golpista operando várias vítimas (redes de centenas de contas ligadas por aparelho). 3+ para não pegar o celular da família |
| `new_channel` | conta que já faz Pix aparece por um canal que nunca usou (fora do cold start) | +5 | Desvio de hábito fraco |
| `far_from_last_location` | > 200 km do último Pix com localização: +10; > 1.000 km: +15 | +10/+15 | Celular em outra mão. Viagem explica parte, por isso peso moderado |
| `impossible_travel` | velocidade > 900 km/h e distância > 100 km (substitui o anterior) | +25 | Fisicamente impossível ser a mesma pessoa no mesmo aparelho. 900 km/h ≈ avião comercial, o limiar usual de mercado |

### E.2 Magnitude (`magnitude`) — o valor foge do habitual?

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `amount_above_profile` | `8 · log2(amount_ratio)`, se o valor passa do habitual; máximo 30 | 0–30 | Cada vez que o valor dobra acima do habitual, a chance de fraude sobe ~1,7× (8 pontos). Contínuo, para não haver degrau que o golpista explore ("mande R$ 1 a menos"). Exigido pelo BC: transação "não compatível com o perfil" (art. 89) |
| `balance_drain` | valor ÷ saldo ≥ 50%: +8; ≥ 80%: +16; ≥ 95%: +24 | 8–24 | "Zera a conta": assinatura da falsa central e do sequestro. Aluguel e fatura também levam boa parte do saldo; quem compensa é o mitigante de recorrência |

### E.3 Ritmo e acumulado (`velocity`)

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `velocity_spike` | tentativas em 24h (com esta) ≥ 3× o ritmo habitual e ≥ 5: +10; ≥ 6× e ≥ 8: +20 | 10–20 | O golpista tira o máximo antes de ser percebido. Os mínimos absolutos (5, 8) evitam disparar em quem quase não usa Pix |
| `new_payee_burst` | destinos novos no período = 2: +8; ≥ 3: +15 | 8–15 | Pessoa normal raramente paga vários estranhos no mesmo período (para o Fed, 3 transferências para beneficiários novos em 30 min já são alto risco) |
| `high_outflow_ratio` | já houve saída nas 24h **e** `exit_ratio_with_pix` ≥ 70%: +10; ≥ 90%: +18 | 10–18 | Pega o roubo com "intervalo calculado": olha o acumulado, não a velocidade. Exige saída anterior para não repetir o `balance_drain` |
| `retry_after_block` | Pix para este destino com 2FA ou rejeição (sem ser só limite) nas últimas 24h | +20 | "Faz de novo que agora vai" é roteiro de golpe |
| `split_payments` | 3º Pix para o mesmo destino em 24h, com valor a ±10% do anterior | +10 | Fracionamento para fugir de limite. Mesada e pagamentos de família têm valores diferentes. Sensível a PLD |

Velocidade nunca é teto: o Regulamento proíbe limitar o número de
transações (art. 37-A).

### E.4 Relação (`relationship`) — o pagador conhece o destino?

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `first_payment_to_destination` | `first_payment` e não é conta própria | +15 | 67% da fraude está nos 7% de pagamentos a beneficiário novo (NICE, LR ≈ 9,6, o que daria ~33 pontos). Usamos LR 2,8: a nossa "primeira vez" é mais grosseira e muito Pix legítimo é para gente nova. Fator do BC: "recorrência entre os dois usuários" (art. 39-B) |
| `own_account_new` | mesmo titular e conta destino < 30 dias | +15 | "Conta segura" aberta pelo golpista em nome da vítima. Também é portabilidade legítima: por isso nunca rejeita sozinho |
| `escalating_payments` | `escalating` | +15 | Investimento, amor e tarefas começam pequeno e crescem (no Reino Unido, romance tem ~10 pagamentos por caso) |
| `test_then_large` | relação < 24h, já houve Pix de até R$ 20 e este é ≥ 10× maior (sem ser `escalating`) | +10 | Indicador do GAFI ("pagamento pequeno seguido de valores maiores"). Peso baixo: muita gente testa a conta com R$ 1 |
| `recurring_destination` | `recurring` | **−20** | Aluguel, família, contas. Alivia só o score, nunca o limite regulatório |
| `received_from_destination` | `two_way` e não escalando | **−10** | Relação de mão dupla (amigo, reembolso) |
| `own_account_established` | mesmo titular e conta destino ≥ 180 dias | **−20** | Transferência entre contas próprias antigas |

### E.5 Destino (`destination`) — quem recebe é confiável?

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `dict_history` | marcação válida mais forte: laranja/golpista/identidade falsa ≤ 12 meses +40, > 12 meses +20; `OTHER`/`UNKNOWN` ≤ 12 meses +15, > 12 meses +5 | 5–40 | Reputação compartilhada entre os bancos, com peso que cai com o tempo. Uso do DICT é obrigatório (art. 89). Em 2024 foram 1,22 milhão de marcações, 38% de golpista e 27% de laranja |
| `new_destination_account` | conta destino < 7 dias: +40; < 30: +30; < 90: +15; < 180: +5 (não vale para conta própria) | 5–40 | Fator que o BC manda olhar (art. 39-B). No Reino Unido, 47% das laranjas encerradas tinham < 1 ano e 74% nas fintechs tinham ≤ 6 meses (FCA). Escada decrescente porque metade das laranjas é conta antiga alugada |
| `destination_fan_in` | `fan_in` ≥ 2: +10; ≥ 4: +25; ≥ 8: +40 (PJ: limiares × 3) | 10–40 | Várias vítimas pagando a mesma conta (Carta Circular IV-n; regra de mercado: ≥ 3 pagadores em 7 dias). O sinal de laranja visível até em conta de outro banco |
| `destination_rejected_before` | outros clientes com Pix para este destino rejeitado por suspeita de destino em 90 dias: 1 → +25; 2 → +40; ≥ 3 → +50 | 25–50 | O próprio motor já viu fundada suspeita nesse destino com **outros** clientes. Sem operacionais e sem "só limite" |
| `destination_pass_through` | destino nosso que repassou ≥ 80% do que entrou nas 24h, com entrada ≥ R$ 500: +20; com ≥ 3 pagadores novos: +30 | 20–30 | "Conta que não acumula" (Carta Circular IV-k) |
| `destination_inflow_jump` | destino nosso com `inflow_jump` ≥ 3: +15; ≥ 10: +30 | 15–30 | "Movimentação incompatível com a capacidade financeira" (IV-a), medida contra o próprio histórico, já que não usamos renda |
| `destination_dormant_awakened` | destino nosso `dormant` com ≥ 3 entradas nas 24h | +20 | Conta parada que acorda recebendo de vários: comprada ou alugada (IV-e) |
| `destination_block_history` | destino nosso: +10 por bloqueio passado (até +20); +15 se já teve Pix recebido rejeitado por suspeita | 10–35 | Histórico de problemas no destino |

### E.6 Pagador como laranja (`payer_mule`) — está repassando dinheiro de outros?

Todos sensíveis a PLD: na resposta pública viram `risk_policy`.

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `payer_pass_through` | ≥ 2 pagadores novos nas 24h, `pass_through_with_pix` ≥ 80% e entrada 24h ≥ metade deste Pix: +20; com ≥ 4 pagadores novos: +30 | 20–30 | Recebe de vários desconhecidos e repassa quase tudo: conta de passagem (Carta Circular IV-k, IV-ad) |
| `new_source_account` | junto com `payer_pass_through`, conta pagadora < 30 dias | +10 | Conta nova repassando. Sozinha, idade da conta não soma: nunca punir só por falta de histórico |
| `payer_inflow_jump` | `inflow_jump` do pagador ≥ 3: +10; ≥ 10: +20 | 10–20 | Entrou num dia muito mais do que costuma entrar num mês (IV-a) |
| `payer_dormant_awakened` | pagador `dormant` com ≥ 2 entradas nas 24h | +15 | Conta parada que volta a movimentar de repente (IV-e) |

**Base para rejeitar:** o que obriga a rejeitar é **fundada suspeita de
fraude** (art. 38, II), não suspeita de lavagem. A laranja que repassa dinheiro
recém-recebido de vítimas está no meio de uma fraude; por isso o motor só
rejeita com passagem + pagadores novos + um terceiro elemento (assinatura
`mule_cashout`).

### E.7 Contexto (`context`)

| Código | Condição | Pts | Por quê |
|---|---|---|---|
| `unusual_night` | período noturno e < 10% das saídas do cliente são à noite | +10 | Madrugada fora do hábito (horário é fator do art. 39-B). Quem sempre usa à noite não é penalizado |
| `source_risk_history` | pagador com bloqueio no histórico: +5; com Pix de saída rejeitado por suspeita: +5 | 5–10 | Vítima recorrente ou conta comprometida |
| `dict_unavailable` | sem DICT recente, destino externo e relação nova | +5 | Não sabemos, então não aliviamos (o piso de 2FA vem da regra dura) |
| `missing_geolocation` | Pix sem geolocalização (fora do cold start) | +5 | O BC deixa reduzir o limite quando não dá para localizar o aparelho (IN 512, § 15). Fraco: o campo é opcional |

Idade, renda e profissão **não entram em nenhum sinal**.

---

## F. Assinaturas

O score trata os sinais como independentes, o que **subestima** combinações
raras: fraude é conjunção. Estas regras somam um bônus quando o padrão
completo de um golpe aparece. Família própria (`pattern`, teto 40), e cada
uma carrega o ρ da ameaça que representa.

| Código | Golpe | Condição | Pts | ρ | Por quê do ρ / detalhe |
|---|---|---|---|---|---|
| `scam_drain_pattern` | Falsa central, falso parente, extorsão | primeira vez **e** não é conta própria **e** sem `payer_pass_through` **e** valor ≥ 80% do saldo **e** (destino < 90 dias **ou** `fan_in ≥ 2`) | +20 | 0,2 | Golpe autorizado: a vítima confirma. Não dispara na conta própria nem na laranja pagadora, que têm assinatura própria |
| `safe_account_pattern` | Conta segura | mesmo titular **e** destino < 30 dias **e** valor ≥ 50% do saldo | +20 | 0,2 | Idem |
| `refund_to_third_party` | Pix errado / devolução | entrou em 24h, de uma contraparte nova e diferente do destino, um valor a ±5% deste Pix **e** primeira vez para o destino | +20 | 0,2 | Devolução de verdade se faz pela função de devolução, que volta para quem pagou |
| `scam_ladder` | Investimento, amor, tarefas | `escalating` **e** destino < 180 dias | +15 | 0,2 | O escalonamento contra destino antigo (empreiteiro em parcelas) fica sem o bônus |
| `takeover_cashout` | Roubo de usuário | aparelho não cadastrado **e** primeira vez **e** (≥ 3× o habitual **ou** ≥ 50% do saldo) | +15 | 0,9 | Ameaça de identidade: o 2FA resolve |
| `night_coercion` | Roubo noturno, sequestro | noite **e** ≥ 2 destinos novos no período **e** `exit_ratio_with_pix` ≥ 50% | +25 | 0,4 | No roubo do aparelho o ladrão não passa na biometria; no sequestro a vítima passa |
| `fresh_mule` | Laranja no destino | (destino < 30 dias **e** `fan_in` ≥ 2, PJ × 3, não é conta própria) **ou** (destino nosso com passagem ≥ 80%, ≥ 3 pagadores novos em 24h, PJ × 3, **e** conta < 90 dias **ou** `inflow_jump` ≥ 3) | +30 | 0,1 | O maior bônus: a laranja é o que liga as vítimas |
| `mule_cashout` | Laranja no pagador | `payer_pass_through` **e** primeira vez **e** um terceiro elemento: destino < 180 dias, `fan_in` ≥ 2, marcação no DICT, pagador dormente ou `inflow_jump` ≥ 10 | +25 | 0,1 | O terceiro elemento separa a laranja do racha, da vaquinha e do autônomo que paga o fornecedor: esses ficam com `payer_pass_through` e o alerta de PLD, sem o bônus |

---

## G. Score

```
pontos da família = min(soma dos pontos positivos da família, teto)
pontos            = Σ pontos das famílias + max(Σ mitigantes, −40)
P                 = 1 / (1 + 10.000 · 2^(−pontos/10))
ρ do Pix          = Σ(pontos da família × ρ) / Σ pontos positivos
```

- Dentro de uma família, o ρ é a média dos ρ dos sinais ponderada pelos
  pontos (as assinaturas trazem o próprio ρ).
- ρ ponderado responde "de que tipo é a evidência": se a maior parte é de
  identidade, ρ ≥ 0,5 e o 2FA resolve; se é de golpe ou laranja, ρ fica baixo
  e o 2FA não resolve.
- **Ameaça** (camada interna): `identidade` se ρ ≥ 0,5; `laranja` se metade
  ou mais dos pontos vêm de destino, pagador-laranja e assinaturas de
  laranja; senão `golpe`.

---

## H. Política e custos

### H.1 Os custos

Para um Pix com probabilidade de fraude P e valor V (em reais):

```
custo(aprovar)  = P · V
custo(2FA)      = c₂ + P · V · (1 − ρ)
custo(rejeitar) = (1 − P) · (c_r + α · V)
```

| Parâmetro | Valor | O que é | Por que esse valor |
|---|---|---|---|
| `C_2FA` (c₂) | R$ 3 | Custo de pedir confirmação a um cliente legítimo: atrito, abandono, ligação ao SAC | Escolhido para a taxa de 2FA em legítimos ficar em 3–5%, o orçamento usual de desafio no mercado (1–5%). É o parâmetro que mais muda a fricção |
| `C_REJECT` (c_r) | R$ 20 | Custo fixo de barrar um legítimo: SAC, retrabalho, liberação manual | Ordem de grandeza de um atendimento. Só aparece na derivação dos cortes |
| `ALPHA` (α) | 10% | Parte do custo de barrar um legítimo proporcional ao valor: irritação, risco de perder o cliente | Barrar um Pix de R$ 50 mil é bem pior que um de R$ 50. Só na derivação dos cortes |

### H.2 Os cortes

A conta acima, resolvida, vira regras de corte (`policy.py`):

| # | Situação | Decisão | `rule` | Por quê |
|---|---|---|---|---|
| 1 | regra dura de rejeição | `rejected` | `regra_dura` | Obrigação ou fato (B) |
| 2 | P ≥ 50% | `rejected` | `risco_claro` | Mais provável fraude do que não. Pelo custo, nem a identidade compensa o 2FA daí para cima (com ρ = 0,9, o 2FA ainda deixa passar 10% das fraudes) |
| 3 | 10% ≤ P < 50% e ρ < 0,5 | `rejected` | `fundada_suspeita` | Fundada suspeita de golpe ou laranja; o 2FA não resolve, a vítima (ou o dono da laranja) confirma |
| 4 | 10% ≤ P < 50% e ρ ≥ 0,5 | `two_factor_required` | `identidade` | Suspeita forte, mas de identidade: o 2FA barra quem não é o dono. Pelo custo, com ρ = 0,9 o 2FA segue mais barato que rejeitar até P ≈ 50% |
| 5 | P < 10% e P × V × ρ > R$ 3 | `two_factor_required` | `suspeita` | Abaixo de 10% a comparação é aprovar × 2FA: o 2FA ganha quando a fraude que ele evita (P·V·ρ) vale mais que o atrito (c₂) |
| 6 | senão | `approved` | `risco_baixo` | Risco baixo para o valor |
| — | piso de regra dura acima do resultado | `two_factor_required` | `regra_dura` | Nenhuma camada desce a severidade; empate fica com a regra dura |

| Parâmetro | Valor | Por quê |
|---|---|---|
| `P_FUNDADA_SUSPEITA` | 10% | Com ρ ≥ 0,1 e α = 10%, rejeitar nunca é a ação de menor custo abaixo de 10% (o corte exato é `(17 + 0,1V) / (20 + V)`, que tende a 10% nos valores altos). Na margem, ~9 legítimos barrados por fraude barrada; a média dos rejeitados é melhor que a margem (programas maduros miram ~5:1 no total) |
| `P_RISCO_CLARO` | 50% | Ver linha 2 |
| `RHO_IDENTITY` | 0,5 | Metade ou mais da evidência é de "não é o dono" |

**Desvio deliberado da teoria:** pelo custo exato, um Pix de R$ 200 com
P = 17% e ρ = 0,13 para uma laranja ficaria em 2FA (custo do 2FA ≈ R$ 32,6
contra ≈ R$ 33,2 de rejeitar, por causa dos R$ 20 fixos de barrar um
legítimo). Mas pagar laranja é fundada suspeita, e a norma manda rejeitar
qualquer que seja o valor. O corte único de 10% é escolha de compliance.

**Simplificação aceita:** evidência mista (ρ entre 0,5 e 0,7) com P entre
~20% e 50% recebe 2FA, quando o custo exato daria rejeição. É raro e fica do
lado da fricção.

### H.3 P mínima para pedir 2FA

Entre parênteses, os pontos equivalentes.

| Valor | Identidade (ρ = 0,9) | Golpe (ρ = 0,4) | Laranja (ρ = 0,1) |
|---|---|---|---|
| R$ 100 | 3,3% (84) | 7,5% (97) | não pede: aprova até 10% e rejeita dali em diante |
| R$ 1.000 | 0,33% (51) | 0,75% (62) | 3% (83) |
| R$ 5.000 | 0,07% (27) | 0,15% (39) | 0,6% (59) |
| R$ 20.000 | 0,02% (7) | 0,04% (19) | 0,15% (39) |

### H.4 Como isso conversa com o BC

- `rejected` = **fundada suspeita**: o BC manda rejeitar (art. 38, II;
  Res. 142, art. 2º-A). Os critérios são nossos, e este dicionário é a
  documentação que a norma pede (art. 89, § 4º).
- `two_factor_required` = **suspeita**. Contra invasão, o 2FA é a defesa
  certa. Contra golpe autorizado ele não segura: a defesa da norma é o
  **temporizador** (reter 30–60 min avisando o cliente). Como a API só tem três
  status, o 2FA de golpe sai com `hold_recommended = true` e um alerta
  específico.

---

## I. Liberação manual

Fora do motor, no controller, **depois** da decisão.

- Pix não aprovado + liberação aberta do mesmo pagador e destino +
  `max_amount` ≥ valor + validade ≥ data do Pix → `approved`. Uso único;
  validade padrão de 1h. Grava o que foi desfeito (`overridden_status`,
  `overridden_reasons`).
- O operador pode desfazer uma suspeita ("conferi, não é golpe"), mas não uma
  regra que o banco é obrigado a cumprir. Se o Pix foi barrado por um destes
  motivos, a liberação é ignorada e continua disponível
  (`NOT_RELEASABLE` em `reasons.py`): `limit_exceeded`, `dict_fraud_marker`,
  `sanctioned_party`, `betting_destination`, `destination_account_blocked`,
  `new_device_limit`, `new_device_structuring` (o limite do aparelho é do BC;
  o caminho é cadastrar o aparelho) e `engine_error`.
- O Pix liberado entra no histórico, e o destino passa a ser conhecido.

---

## J. Resposta

| Campo | Onde | Conteúdo |
|---|---|---|
| `reasons` | pública | regras duras que dispararam + os 3 sinais de maior peso, com mensagens qualitativas (nada de números exatos nem de outros clientes, por sigilo bancário). Atende o direito de revisão de decisão automatizada (LGPD, art. 20) |
| `risk_policy` | pública | substitui **todos** os motivos sensíveis a PLD: `payer_pass_through`, `payer_inflow_jump`, `payer_dormant_awakened`, `new_source_account`, `mule_cashout`, `split_payments`, `new_device_structuring`. Avisar o cliente de suspeita de lavagem é proibido (Lei 9.613, art. 11, II; Circular 3.978, art. 50) |
| `alert` | pública | só no 2FA, montado a partir do sinal mais forte (ex.: conta segura: "O banco nunca pede para transferir seu dinheiro para uma 'conta segura'.") |
| `hold_recommended` | pública | `true` no 2FA de golpe ou laranja (ρ < 0,5): em produção, retenção pelo temporizador |
| sinais, pontos, P, ρ, família, `rule` | interna | tudo que o motor calculou |
| `threat` | interna | `identidade`, `golpe` ou `laranja` (G) |
| `situation_type` | interna | causa no vocabulário do DICT para a notificação de infração: `ACCOUNT_TAKEOVER`, `COERCION` ou `SCAM` |
| `basis` | interna | `own_evidence` ou `third_party_mark` (rejeição só por marcação de outro banco não abre notificação nova) |
| `pld_alert` | interna | `payer_mule` ≥ 20 pontos, ou `mule_cashout`, `split_payments` ou `new_device_structuring`. Não muda a decisão: marca o Pix para a equipe de PLD |
| `sanctions_freeze` | interna | `true` em `sanctioned_party` (indisponibilidade de ativos e comunicação ao BC, MJSP e COAF ficam fora do escopo) |
