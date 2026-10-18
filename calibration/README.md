# Calibração do motor por cenários

Bateria de cenários escrita por agentes **sem acesso ao motor** e busca dos
pesos/política que minimizam o custo real. O DICT não é consultado: a
resposta dele vem pronta no cenário.

```bash
python calibration/calibrate.py --baseline              # motor atual nos cenários
python calibration/calibrate.py                         # busca + validação cruzada → results/best.json
python calibration/calibrate.py --skip-difficulty hard  # idem, sem os casos "indistinguíveis"
```

## Peças

| Arquivo | O que é |
|---|---|
| `schema.md` | o formato dos cenários: a única coisa que os agentes geradores leram |
| `data/gen_*.json` | 240 cenários: 60 golpes de engenharia social, 60 de invasão/laranja, 60 legítimos comuns, 60 legítimos que parecem suspeitos |
| `data/review*.json` | revisão de coerência por outros 2 agentes cegos: 2 descartados, 3 corrigidos |
| `data/payer_dict.json` | o DICT do **pagador**, anotado depois por outro agente cego (só leu o schema e os cenários): 15 cenários com marcação |
| `scenario.py` | cenário → `Features` |
| `cost.py` | o juiz: custo real de cada decisão (separado dos custos internos do motor, que a busca ajusta) |
| `calibrate.py` | roda o motor de verdade até os sinais, re-soma com cada configuração e busca a melhor |

A busca mexe em: multiplicador de pontos por família, tetos, ρ, prior,
cortes de P, c₂, custo de rejeitar e a política (cortes atuais × custo
esperado puro). **Não mexe** nas regras duras nem nos limiares de cada
sinal. Para não premiar sorte: penalidade por se afastar do motor atual,
média do custo relativo em 3 pesos de legítimo (10, 50, 200 clientes bons
por golpe) e validação cruzada em 5 partes (busca em 4, mede na 5ª).

## Resultado (238 cenários)

| | motor atual | calibrado, fora da amostra |
|---|---|---|
| custo relativo | 1,00 | **1,16** (partes: 1,0 / 1,0 / 1,80 / 1,04 / 0,94) |
| golpes aprovados | 57 de 119 | 44 |
| valor de golpe perdido | 47% | 53% |

**A calibração não melhora o motor.** O que a busca ganha no treino some
(ou piora) nos cenários que ela não viu. A configuração escolhida com todos
os dados fica praticamente igual à atual (distância 0,58: P de fundada
suspeita 0,10→0,099, ρ de identidade 0,5→0,34) e não muda nenhum cenário
âncora (L e G do 4.2).

**Por quê:** das 57 fraudes aprovadas, 40 são "hard". Nelas o único sinal
é `first_payment_to_destination` (ou nenhum). Nos dados elas são idênticas
a um legítimo pagando alguém novo, e nenhum peso as separa sem barrar os
legítimos iguais.

**Sem os "hard"** (158 cenários): fora da amostra 0,87, mas instável
(partes de 0,09 a 2,99). A direção: destino ×3, prior ×4 e política de custo
esperado puro. Rejeita muito mais golpe, mas quebra 20 dos 45 cenários
âncora e passa a rejeitar legítimos. É indício, não resultado.

## DICT do pagador

O motor passou a ler o DICT da conta que envia (uma consulta por dia, no
resumo diário). Para medir, outro agente cego anotou o que o DICT mostraria
de cada pagador: 6 de 120 legítimos com alguma marcação (fraude de abertura
antiga, marcação resolvida ou errada), 6 de 20 pagadores-laranja marcados e
3 vítimas com marcação plausível.

| | antes | regra `payer_dict_fraud_marker` |
|---|---|---|
| golpes aprovados | 57 | **56** |
| golpes rejeitados | 35 | **36** |
| legítimos rejeitados | 3 | 3 |
| custo (peso 10 / 50 / 200) | 302.756 / 342.832 / 493.117 | **301.766 / 341.842 / 492.127** |

Melhora pequena e só para um lado: os pagadores-laranja marcados quase todos
já eram rejeitados pelo repasse. Testado e descartado: a marcação como sinal
de score (+20/+40). Ela barrava um legítimo com marcação errada (ambulante
que recebe de muita gente de madrugada) e piorava o custo. Por isso a
marcação sozinha só liga o alerta de PLD.

`tests/unit/engine/test_bench.py` roda esta bancada no pytest como teste de
não-regressão (o placar não pode piorar).

## O que fazer com isso

1. **Manter os pesos atuais.** Não há evidência de combinação melhor.
2. O ganho está em **informação nova**, não em peso. As fraudes perdidas
   pedem sinais que o motor não tem hoje: chamada telefônica em curso /
   app de acesso remoto aberto, tempo na tela de confirmação, contato
   recém-adicionado, primeira vez que o destino aparece no banco inteiro
   (não só para este cliente) para valores altos.
3. Se o destino tiver mais peso no futuro, recalibrar com dados reais (MED).
   Para isso basta trocar `data/` por casos reais no mesmo formato.

Limites: rótulos e dados vêm de LLM (revisados por outra LLM, não por
gente); o peso de legítimos por golpe é uma premissa; o custo do 2FA
(chance de parar: invasor 90%, enganado 20%, laranja 5%) também.
