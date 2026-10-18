# Formato de um cenário de Pix

Cada cenário descreve **um Pix enviado** por um cliente do nosso banco e tudo
o que o banco sabe naquele instante. Um arquivo é um JSON com uma lista de
cenários. Valores em **reais** (número, ex.: `1500.0`). Campos omitidos
assumem o valor padrão indicado (o padrão é um cliente comum, sem nada de
estranho).

```jsonc
{
  "id": "string única, ex. 'se-017'",
  "narrative": "1 a 3 frases: o que está acontecendo de verdade",
  "label": "fraud" | "legit",          // verdade: é golpe/fraude ou é legítimo?
  "fraud_type": "string ou null",      // ex. 'falsa_central', 'roubo_celular', 'laranja_destino'...
  "operator": "owner" | "intruder",    // quem apertou o botão: o próprio dono da conta
                                       // (mesmo enganado/coagido, ou ele mesmo sendo laranja)
                                       // ou outra pessoa usando a conta dele
  "difficulty": "easy" | "medium" | "hard",   // quão difícil é perceber pelo que o banco vê

  "pix": {
    "amount": 150.0,                   // valor deste Pix
    "hour": 14                         // hora local (0-23). Noite = 20h às 6h
  },

  "payer": {                           // o cliente que envia
    "type": "PF",                      // "PF" ou "PJ"
    "age_years": 41,                   // idade da pessoa (PJ: anos da empresa)
    "account_age_days": 600,           // há quantos dias a conta existe
    "balance": 5000.0,                 // saldo antes deste Pix
    "history_days": 30,                // dias de histórico nos últimos 30 (conta nova: menos)
    "pix_out_per_day": 0.8,            // média de Pix enviados por dia (30 dias)
    "typical_large_pix": 400.0,        // um Pix "grande" habitual dele (percentil 90). null = nunca enviou
    "avg_pix_out": 150.0,              // valor médio dos Pix enviados. null = nunca enviou
    "avg_pix_in": 2000.0,              // valor médio dos Pix recebidos
    "pix_in_per_day": 0.2,             // média de Pix recebidos por dia
    "night_share": 0.2,                // fração dos Pix dele feitos à noite (0-1)
    "daily_limit": 10000.0,            // limite diurno configurado
    "nightly_limit": 1000.0,           // limite noturno configurado
    "past_account_blocks": 0,          // vezes que a conta foi bloqueada no passado
    "past_rejected_pix": 0,            // Pix dele já rejeitados por suspeita no passado
    "restricted": null                 // null | "csnu" (lista de sanções da ONU)
  },

  "flow_24h": {                        // movimentação do pagador nas últimas 24h ANTES deste Pix
    "inflow_amount": 0.0,              // quanto entrou
    "inflow_count": 0,                 // quantos Pix entraram
    "inflow_new_senders": 0,           // de quantas pessoas que nunca tinham mandado nada antes
    "outflow_amount": 0.0,             // quanto já saiu
    "outflow_count": 0,                // quantos Pix já saíram
    "outflow_new_recipients": 0,       // quantos desses foram para destinos novos (neste período dia/noite)
    "matching_inflow_from_stranger": false  // entrou, de um desconhecido, um valor ±5% igual a este Pix
  },

  "device": {
    "registered": true,               // celular já usado e confiável nesta conta (vários dias, há > 7 dias)
    "other_registered_devices": 1,     // quantos OUTROS celulares confiáveis a conta tem
    "ip_seen_before": true,
    "has_geolocation": true,           // o app enviou localização
    "distance_from_last_km": 0.4,      // distância do último Pix com localização (null = sem dado)
    "minutes_since_last_location": 600,
    "other_accounts_on_device_30d": 0, // outras contas do banco usadas neste celular em 30 dias
    "channel_used_before": true,       // a conta já usou este canal (app/web) antes
    "unregistered_sent_today": 0.0,    // já enviado hoje de celulares não confiáveis
    "near_200_from_unregistered_24h": 0  // Pix de R$180-200 de celular não confiável em 24h
  },

  "velocity": {
    "attempts_1h": 0,                  // tentativas de Pix do pagador na última hora (qualquer resultado)
    "attempts_24h": 1,
    "seconds_since_last_attempt": 36000
  },

  "destination": {                     // quem recebe
    "bank": "other",                   // "same" (cliente nosso) ou "other" (outro banco)
    "type": "PF",
    "account_age_days": 900,           // idade da conta que recebe
    "same_owner": false,               // é do mesmo CPF/CNPJ do pagador?
    "other_clients_first_paid_7d": 0,  // outros clientes nossos que pagaram este destino pela 1ª vez em 7 dias
    "other_clients_rejected_90d": 0,   // outros clientes nossos com Pix para ele rejeitado por suspeita (90 dias)
    "restricted": null,                // null | "bets" (casa de apostas) | "csnu"
    "dict": {                          // diretório central do Banco Central
      "available": true,               // respondeu agora?
      "markers": []                    // marcações de fraude feitas por qualquer banco:
                                       // [{"type": "MULE_ACCOUNT"|"SCAMMER_ACCOUNT"|"APPLICATION_FRAUD"|"OTHER",
                                       //   "on": "account"|"owner", "days_ago": 30}]
    },
    "internal": null                   // só se bank = "same": o que sabemos da conta que recebe:
                                       // {"blocked": false, "balance": 1000.0, "history_days": 30,
                                       //  "pix_in_per_day": 0.2, "avg_pix_in": 500.0, "pix_out_per_day": 0.5,
                                       //  "inflow_24h_amount": 0.0, "inflow_24h_count": 0, "inflow_24h_new_senders": 0,
                                       //  "outflow_24h_amount": 0.0, "past_account_blocks": 0, "past_rejected_pix_in": 0}
  },

  "relationship": {                    // o pagador já conhece este destino?
    "previous_payments": 3,            // Pix aprovados antes para este destino
    "previous_total": 300.0,
    "largest_previous": 120.0,
    "first_payment_days_ago": 60,
    "last_payment_days_ago": 5,
    "received_from_destination_total": 0.0,   // quanto o destino já mandou para o pagador
    "first_received_days_ago": null,
    "attempts_to_destination_24h": 0,  // tentativas para este destino nas últimas 24h
    "last_attempt_amount": null,
    "blocked_attempts_24h": 0,         // dessas, quantas pediram confirmação ou foram barradas
    "fraud_rejections_24h": 0          // dessas, quantas foram rejeitadas por suspeita
  }
}
```

Atenção ao bloco `relationship`: se ele for **omitido**, vale o padrão acima
(destino conhecido, 3 pagamentos). Se ele **aparecer**, todo campo omitido
dentro dele vale 0/null. Destino novo (nunca pago):
`"relationship": {"previous_payments": 0}`.
