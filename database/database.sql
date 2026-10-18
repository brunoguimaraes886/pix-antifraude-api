-- ─────────────────────────────────────────────────────────────────
-- Pix Antifraude — schema
--
-- Convenções: id SERIAL, uma *_key CHAR(36) pública onde a linha é
-- exposta, created_at em todas (quando a linha foi gravada AQUI — não
-- entra no motor). Valores em centavos (BIGINT). Datas com fuso
-- (TIMESTAMPTZ). Documento (CPF/CNPJ) só com dígitos: 11 = PF, 14 = PJ.
-- ─────────────────────────────────────────────────────────────────


-- ── Perfil (vem do seed; onboarding está fora do escopo) ─────────

CREATE TABLE customer(
    id                              SERIAL PRIMARY KEY,
    customer_key                    CHAR(36) NOT NULL,
    document_number                 VARCHAR(14) NOT NULL,
    name                            VARCHAR(255) NOT NULL,
    -- Nascimento (PF) ou fundação (PJ).
    birth_date                      DATE NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(customer_key),
    UNIQUE(document_number),
    CHECK (document_number ~ '^([0-9]{11}|[0-9]{14})$')
);

CREATE TABLE account(
    id                              SERIAL PRIMARY KEY,
    account_key                     CHAR(36) NOT NULL,
    customer_id                     INTEGER NOT NULL REFERENCES customer(id),
    branch                          VARCHAR(4) NOT NULL,
    account_number                  VARCHAR(20) NOT NULL,
    -- Abertura da conta no banco. É ela que dá a idade da conta.
    opening_date                    TIMESTAMPTZ NOT NULL,
    -- Saldo atual. Nasce no seed e só muda com Pix aprovado.
    balance                         BIGINT NOT NULL,
    -- Limite do período diurno (6h–20h) e do noturno (20h–6h). O noturno vale
    -- à noite para qualquer destino (PF, PJ ou conta própria).
    daily_limit                     BIGINT NOT NULL,
    nightly_limit                   BIGINT NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(account_key),
    UNIQUE(branch, account_number),
    CHECK (balance >= 0),
    CHECK (daily_limit >= 0 AND nightly_limit >= 0)
);

CREATE INDEX ix_account_customer ON account(customer_id);

-- Bloqueio da própria conta. ended_at vazio = bloqueada agora.
-- (Bloqueio de Pix não tem tabela: é o Pix com análise "rejected".)
CREATE TABLE account_block(
    id                              SERIAL PRIMARY KEY,
    account_id                      INTEGER NOT NULL REFERENCES account(id),
    reason                          VARCHAR(255) NOT NULL,
    started_at                      TIMESTAMPTZ NOT NULL,
    ended_at                        TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX ix_account_block_account ON account_block(account_id);

-- Listas restritivas: sanções do CSNU (ONU), operadoras de apostas e
-- ordens judiciais. Carregadas no seed; na vida real vêm de fora (lista do
-- CSNU, Secretaria de Prêmios e Apostas, Judiciário).
CREATE TABLE restricted_party(
    id                              SERIAL PRIMARY KEY,
    document_number                 VARCHAR(14) NOT NULL,
    -- csnu, bets ou court_order.
    list                            VARCHAR(20) NOT NULL,
    reason                          VARCHAR(255) NOT NULL,
    listed_at                       DATE NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(document_number, list),
    CHECK (list IN ('csnu', 'bets', 'court_order'))
);


-- ── Resumo diário do histórico (o "habitual" da conta) ──────────
-- Uma linha por conta por dia, calculada sob demanda no primeiro Pix do
-- dia da conta, a partir dos últimos 30 dias do extrato.

CREATE TABLE account_baseline(
    id                              SERIAL PRIMARY KEY,
    account_id                      INTEGER NOT NULL REFERENCES account(id),
    baseline_date                   DATE NOT NULL,
    -- Vazios quando a conta não teve movimento naquele sentido na janela.
    avg_out_amount                  BIGINT,
    p90_out_amount                  BIGINT,
    avg_in_amount                   BIGINT,
    p90_in_amount                   BIGINT,
    avg_daily_out_count             NUMERIC(10, 2),
    avg_daily_in_count              NUMERIC(10, 2),
    -- Dias da janela em que a conta já existia (0 a 30).
    history_days                    INTEGER NOT NULL,
    -- Fração dos Pix de saída da janela no período noturno (20h–6h).
    night_out_share                 NUMERIC(5, 4),
    -- Todo o histórico da conta, não só os 30 dias. Os Pix rejeitados
    -- contam só os rejeitados por suspeita (não os por limite ou motivo
    -- operacional).
    account_block_count             INTEGER NOT NULL,
    rejected_pix_out_count          INTEGER NOT NULL,
    rejected_pix_in_count           INTEGER NOT NULL,
    -- O DICT da própria conta (pagador), uma consulta por dia. Vazio = não
    -- consultado ainda ou o DICT não respondeu (o próximo Pix tenta de novo).
    dict_response                   JSONB,
    dict_fetched_at                 TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(account_id, baseline_date)
);


-- ── Transações ──────────────────────────────────────────────────

-- Tudo que chegou no POST /pix/transaction, inclusive o que foi rejeitado.
CREATE TABLE pix_transaction(
    id                              SERIAL PRIMARY KEY,
    pix_id                          VARCHAR(100) NOT NULL,
    amount                          BIGINT NOT NULL,
    transaction_date                TIMESTAMPTZ NOT NULL,
    -- Vazio quando o pagador não existe no nosso banco (unknown_account).
    source_account_id               INTEGER REFERENCES account(id),
    destination_participant         CHAR(8) NOT NULL,
    destination_branch              VARCHAR(4) NOT NULL,
    destination_account_number      VARCHAR(20) NOT NULL,
    destination_opening_date        TIMESTAMPTZ NOT NULL,
    destination_document_number     VARCHAR(14) NOT NULL,
    -- Preenchido só quando o destino é conta nossa (mesmo ISPB).
    destination_account_id          INTEGER REFERENCES account(id),
    device_id                       VARCHAR(100) NOT NULL,
    channel                         VARCHAR(30) NOT NULL,
    ip                              VARCHAR(45) NOT NULL,
    latitude                        DOUBLE PRECISION,
    longitude                       DOUBLE PRECISION,
    -- O pedido exatamente como chegou (o GET devolve no metadata).
    payload                         JSONB NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(pix_id),
    CHECK (amount > 0)
);

CREATE INDEX ix_pix_transaction_source ON pix_transaction(source_account_id, transaction_date);
CREATE INDEX ix_pix_transaction_destination
    ON pix_transaction(destination_participant, destination_branch, destination_account_number, transaction_date);
CREATE INDEX ix_pix_transaction_destination_document ON pix_transaction(destination_document_number);
CREATE INDEX ix_pix_transaction_destination_account ON pix_transaction(destination_account_id);
CREATE INDEX ix_pix_transaction_device ON pix_transaction(source_account_id, device_id);
CREATE INDEX ix_pix_transaction_source_destination ON pix_transaction(
    source_account_id, destination_participant, destination_branch, destination_account_number, transaction_date
);
CREATE INDEX ix_pix_transaction_device_date ON pix_transaction(device_id, transaction_date);

-- Só dinheiro que de fato moveu: Pix aprovado (uma linha "out" no
-- pagador e, se o destino for nosso, uma "in" no recebedor) ou o
-- histórico que veio do seed (pix_transaction_id vazio).
CREATE TABLE account_statement(
    id                              SERIAL PRIMARY KEY,
    account_id                      INTEGER NOT NULL REFERENCES account(id),
    direction                       VARCHAR(3) NOT NULL,
    amount                          BIGINT NOT NULL,
    counterparty_participant        CHAR(8) NOT NULL,
    counterparty_branch             VARCHAR(4) NOT NULL,
    counterparty_account_number     VARCHAR(20) NOT NULL,
    counterparty_document           VARCHAR(14) NOT NULL,
    occurred_at                     TIMESTAMPTZ NOT NULL,
    pix_transaction_id              INTEGER REFERENCES pix_transaction(id),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    CHECK (direction IN ('in', 'out')),
    CHECK (amount > 0)
);

CREATE INDEX ix_account_statement_account ON account_statement(account_id, occurred_at);
CREATE INDEX ix_account_statement_counterparty
    ON account_statement(account_id, counterparty_participant, counterparty_branch, counterparty_account_number);


-- ── Análise ─────────────────────────────────────────────────────

CREATE TABLE analysis_status(
    id                              SERIAL PRIMARY KEY,
    enumerator                      VARCHAR(50) NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO analysis_status (enumerator) VALUES
('approved'),
('two_factor_required'),
('rejected');

CREATE TABLE transaction_analysis(
    id                              SERIAL PRIMARY KEY,
    -- O "key" da resposta da API.
    analysis_key                    CHAR(36) NOT NULL,
    pix_transaction_id              INTEGER NOT NULL REFERENCES pix_transaction(id),
    status_id                       INTEGER NOT NULL REFERENCES analysis_status(id),
    -- Os pontos do motor (escala de log-odds). Vazio quando o Pix parou
    -- antes do score (recusa operacional ou regra dura sem DICT).
    score                           DOUBLE PRECISION,
    latency_ms                      INTEGER NOT NULL,
    -- Tudo que o motor recebeu. Vazio quando o Pix parou antes do motor
    -- (pagador desconhecido, saldo insuficiente...).
    features                        JSONB,
    -- A resposta do DICT desta consulta. Vazio = o DICT não respondeu.
    dict_response                   JSONB,
    dict_fetched_at                 TIMESTAMPTZ,
    -- Camada interna da decisão: sinais com pontos, P, ρ, ameaça, alertas
    -- de PLD. Nunca sai na resposta da API.
    decision                        JSONB,
    -- Camada pública: alerta ao cliente (só no 2FA) e retenção recomendada.
    alert                           VARCHAR(255),
    hold_recommended                BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(analysis_key),
    UNIQUE(pix_transaction_id)
);

CREATE INDEX ix_transaction_analysis_status ON transaction_analysis(status_id);
CREATE INDEX ix_transaction_analysis_dict ON transaction_analysis(dict_fetched_at) WHERE dict_response IS NOT NULL;

-- Por que a decisão saiu. Mais de uma regra pode disparar; no
-- "approved" não há linha nenhuma.
CREATE TABLE analysis_reason(
    id                              SERIAL PRIMARY KEY,
    analysis_id                     INTEGER NOT NULL REFERENCES transaction_analysis(id),
    reason_code                     VARCHAR(50) NOT NULL,
    message                         VARCHAR(255) NOT NULL,
    -- Pontos do sinal no score. Vazio nas regras duras e operacionais.
    points                          INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW())
);

CREATE INDEX ix_analysis_reason_analysis ON analysis_reason(analysis_id);


-- ── Liberação manual ────────────────────────────────────────────
-- O cliente teve um Pix legítimo barrado, falou com o banco (fora desta
-- API) e um operador libera AQUELE Pix: mesmo pagador, mesmo destino,
-- até um valor, até uma data. Uso único.
--
-- A liberação desfaz a suspeita, não a obrigação: limite, marcação de
-- fraude no DICT, sanções, apostas, destino bloqueado, regras do aparelho
-- não cadastrado e engine_error continuam valendo, e as recusas
-- operacionais (saldo, conta bloqueada) param o Pix antes dela.

CREATE TABLE manual_release(
    id                              SERIAL PRIMARY KEY,
    release_key                     CHAR(36) NOT NULL,
    source_account_id               INTEGER NOT NULL REFERENCES account(id),
    destination_participant         CHAR(8) NOT NULL,
    destination_branch              VARCHAR(4) NOT NULL,
    destination_account_number      VARCHAR(20) NOT NULL,
    max_amount                      BIGINT NOT NULL,
    -- Comparado com o transaction_date do Pix, não com o relógio.
    expires_at                      TIMESTAMPTZ NOT NULL,
    -- Quem liberou e por quê (auditoria).
    operator                        VARCHAR(100) NOT NULL,
    reason                          VARCHAR(255) NOT NULL,
    -- Preenchidos no uso: o Pix liberado e o que o motor tinha decidido.
    pix_transaction_id              INTEGER REFERENCES pix_transaction(id),
    overridden_status               VARCHAR(50),
    overridden_reasons              JSONB,
    used_at                         TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT(NOW()),
    UNIQUE(release_key),
    UNIQUE(pix_transaction_id),
    CHECK (max_amount > 0)
);

CREATE INDEX ix_manual_release_open ON manual_release(source_account_id) WHERE pix_transaction_id IS NULL;
