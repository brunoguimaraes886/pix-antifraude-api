-- ─────────────────────────────────────────────────────────────────
-- Dados de exemplo (PROVISÓRIOS — dados falsos só para a estrutura rodar)
--
-- Onboarding está fora do escopo: clientes e contas nascem aqui. O
-- histórico (extrato) é gerado relativo a NOW(), para que a janela de 30
-- dias do resumo diário sempre tenha movimento quando o banco nasce.
--
-- Nosso ISPB: 88888888. Contas de outro banco usam ISPBs reais só como
-- rótulo (00000000, 60701190, 00360305, 18236120, 60746948).
-- ─────────────────────────────────────────────────────────────────

INSERT INTO customer (customer_key, document_number, name, birth_date) VALUES
('c0000000-0000-4000-8000-000000000001', '12345678909',    'Maria Oliveira',          '1985-04-12'),
('c0000000-0000-4000-8000-000000000002', '52998224725',    'João Pereira',            '1990-05-17'),
('c0000000-0000-4000-8000-000000000003', '39053344705',    'Lucas Souza',             '2004-02-03'),
('c0000000-0000-4000-8000-000000000004', '11222333000181', 'Padaria Pão Quente LTDA', '2012-06-01'),
('c0000000-0000-4000-8000-000000000005', '11144477735',    'Carlos Lima',             '1958-09-21');

-- Maria: a pagadora do exemplo do enunciado (agência 0001, conta 88213).
INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, daily_limit, nightly_limit)
SELECT 'a0000000-0000-4000-8000-000000000001', id, '0001', '88213', '2025-03-02T10:00:00-03:00', 1200000, 1000000, 200000
FROM customer WHERE document_number = '12345678909';

-- João: cliente comum, conta antiga.
INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, daily_limit, nightly_limit)
SELECT 'a0000000-0000-4000-8000-000000000002', id, '0001', '10001', '2019-08-10T09:00:00-03:00', 300000, 500000, 100000
FROM customer WHERE document_number = '52998224725';

-- Lucas: cara de conta laranja (conta nova, entra e sai o tempo todo).
INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, daily_limit, nightly_limit)
SELECT 'a0000000-0000-4000-8000-000000000003', id, '0001', '66666', NOW() - INTERVAL '12 days', 40000, 500000, 100000
FROM customer WHERE document_number = '39053344705';

-- Padaria: PJ que recebe muitos Pix pequenos de clientes diferentes.
INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, daily_limit, nightly_limit)
SELECT 'a0000000-0000-4000-8000-000000000004', id, '0001', '20002', '2012-07-01T09:00:00-03:00', 8000000, 5000000, 1000000
FROM customer WHERE document_number = '11222333000181';

-- Carlos: conta bloqueada agora.
INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, daily_limit, nightly_limit)
SELECT 'a0000000-0000-4000-8000-000000000005', id, '0001', '30003', '2010-01-15T09:00:00-03:00', 500000, 500000, 100000
FROM customer WHERE document_number = '11144477735';

INSERT INTO account_block (account_id, reason, started_at, ended_at)
SELECT id, 'contestação de Pix (MED)', '2024-05-01T10:00:00-03:00', '2024-05-03T10:00:00-03:00'
FROM account WHERE account_number = '30003';

INSERT INTO account_block (account_id, reason, started_at, ended_at)
SELECT id, 'suspeita de fraude', NOW() - INTERVAL '2 days', NULL
FROM account WHERE account_number = '30003';


-- ── Extrato: Maria ──────────────────────────────────────────────
-- Salário todo mês, aluguel todo mês, compras pequenas a cada 2 dias.

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'in', 850000, '00000000', '1234', '700001', '33000167000101',
       date_trunc('day', NOW()) - (m * INTERVAL '30 days') - INTERVAL '3 days' + INTERVAL '12 hours'
FROM account a, generate_series(0, 1) m WHERE a.account_number = '88213';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 250000, '00360305', '0412', '200300', '01234567890',
       date_trunc('day', NOW()) - (m * INTERVAL '30 days') - INTERVAL '2 days' + INTERVAL '13 hours'
FROM account a, generate_series(0, 1) m WHERE a.account_number = '88213';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 4000 + (g * 1373) % 26000,
       CASE g % 3 WHEN 0 THEN '60701190' WHEN 1 THEN '18236120' ELSE '88888888' END,
       CASE g % 3 WHEN 0 THEN '3001' WHEN 1 THEN '0001' ELSE '0001' END,
       CASE g % 3 WHEN 0 THEN '400100' WHEN 1 THEN '500200' ELSE '20002' END,
       CASE g % 3 WHEN 0 THEN '12345678000195' WHEN 1 THEN '98765432000110' ELSE '11222333000181' END,
       date_trunc('day', NOW()) - (g * INTERVAL '2 days') + INTERVAL '12 hours' + ((g % 8) * INTERVAL '1 hour')
FROM account a, generate_series(1, 20) g WHERE a.account_number = '88213';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'in', 5000, '88888888', '0001', '10001', '52998224725',
       date_trunc('day', NOW()) - (g * INTERVAL '10 days') + INTERVAL '15 hours'
FROM account a, generate_series(1, 3) g WHERE a.account_number = '88213';


-- ── Extrato: João ───────────────────────────────────────────────

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'in', 450000, '00000000', '4321', '700002', '00394460000141',
       date_trunc('day', NOW()) - (m * INTERVAL '30 days') - INTERVAL '5 days' + INTERVAL '12 hours'
FROM account a, generate_series(0, 1) m WHERE a.account_number = '10001';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 120000, '60746948', '0100', '300400', '11122233344',
       date_trunc('day', NOW()) - (m * INTERVAL '30 days') - INTERVAL '4 days' + INTERVAL '14 hours'
FROM account a, generate_series(0, 1) m WHERE a.account_number = '10001';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 3000 + (g * 911) % 9000, '60701190', '3001', '400100', '12345678000195',
       date_trunc('day', NOW()) - (g * INTERVAL '3 days') + INTERVAL '18 hours'
FROM account a, generate_series(1, 12) g WHERE a.account_number = '10001';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 5000, '88888888', '0001', '88213', '12345678909',
       date_trunc('day', NOW()) - (g * INTERVAL '10 days') + INTERVAL '15 hours'
FROM account a, generate_series(1, 3) g WHERE a.account_number = '10001';


-- ── Extrato: Lucas (laranja) ────────────────────────────────────
-- 3 Pix por dia de pagadores sempre diferentes; 30 minutos depois, 95%
-- do valor sai para uma de duas contas de outro banco.

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'in', 50000 + (g * 7919) % 200000,
       CASE g % 3 WHEN 0 THEN '60701190' WHEN 1 THEN '00360305' ELSE '60746948' END,
       '0001', '7' || lpad(g::text, 5, '0'), lpad((10000000000 + g * 7919)::text, 11, '0'),
       NOW() - (g * INTERVAL '8 hours')
FROM account a, generate_series(1, 30) g WHERE a.account_number = '66666';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', ((50000 + (g * 7919) % 200000) * 95) / 100,
       CASE g % 2 WHEN 0 THEN '18236120' ELSE '00360305' END,
       '0001',
       CASE g % 2 WHEN 0 THEN '990001' ELSE '990002' END,
       CASE g % 2 WHEN 0 THEN '45678912300' ELSE '32165498700' END,
       NOW() - (g * INTERVAL '8 hours') + INTERVAL '30 minutes'
FROM account a, generate_series(1, 30) g WHERE a.account_number = '66666';


-- ── Extrato: Padaria ────────────────────────────────────────────

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'in', 1500 + (g * 577) % 8000, '18236120', '0001', '9' || lpad(g::text, 5, '0'),
       lpad((20000000000 + g * 104729)::text, 11, '0'),
       date_trunc('day', NOW()) - ((g / 2) * INTERVAL '1 day') + INTERVAL '10 hours' + ((g % 2) * INTERVAL '6 hours')
FROM account a, generate_series(1, 60) g WHERE a.account_number = '20002';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 300000, '00000000', '2001', '880011', '44555666000177',
       date_trunc('day', NOW()) - (g * INTERVAL '7 days') + INTERVAL '9 hours'
FROM account a, generate_series(1, 4) g WHERE a.account_number = '20002';


-- ── Extrato: Carlos ─────────────────────────────────────────────

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'in', 300000, '00000000', '0001', '100001', '29979036000140',
       date_trunc('day', NOW()) - (m * INTERVAL '30 days') - INTERVAL '6 days' + INTERVAL '12 hours'
FROM account a, generate_series(0, 1) m WHERE a.account_number = '30003';

INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, counterparty_branch, counterparty_account_number, counterparty_document, occurred_at)
SELECT a.id, 'out', 2000 + (g * 733) % 6000, '60701190', '3001', '400100', '12345678000195',
       date_trunc('day', NOW()) - (g * INTERVAL '4 days') + INTERVAL '11 hours'
FROM account a, generate_series(1, 8) g WHERE a.account_number = '30003';


-- ── Listas restritivas ──────────────────────────────────────────
-- Exemplos: uma operadora de apostas (betting_destination) e um CPF na
-- lista de sanções do CSNU (sanctioned_party). Na vida real vêm da
-- Secretaria de Prêmios e Apostas e da lista consolidada da ONU.

INSERT INTO restricted_party (document_number, list, reason, listed_at) VALUES
('11444777000161', 'bets', 'Operadora de apostas de quota fixa (exemplo)', '2025-01-01'),
('19119119100',    'csnu', 'Lista consolidada do CSNU (exemplo)',          '2024-06-01');


-- ── Aparelhos cadastrados ───────────────────────────────────────
-- Pela IN BCB 491, o aparelho é "cadastrado" com Pix aprovado em 3 dias
-- distintos, o primeiro há 7 dias ou mais. Sem este histórico todo cliente
-- do seed começaria com aparelho não cadastrado (piso de 2FA acima de
-- R$ 200). Três Pix pequenos, aprovados, há 8, 9 e 10 dias.

INSERT INTO pix_transaction (pix_id, amount, transaction_date, source_account_id, destination_participant,
                             destination_branch, destination_account_number, destination_opening_date,
                             destination_document_number, device_id, channel, ip, latitude, longitude, payload)
SELECT 'seed-' || d.account_number || '-' || g, 1000,
       date_trunc('day', NOW()) - (g * INTERVAL '1 day') + INTERVAL '12 hours',
       a.id, '60701190', '3001', '400100', '2015-01-01T00:00:00-03:00', '12345678000195',
       d.device_id, 'app', '198.51.100.23', -23.56, -46.65, '{"seed": true}'::jsonb
FROM (VALUES ('88213', 'dvc-9f2c71a8'),
             ('10001', 'dvc-joao-1'),
             ('66666', 'dvc-lucas-1'),
             ('20002', 'dvc-padaria-1'),
             ('30003', 'dvc-carlos-1')) AS d(account_number, device_id)
JOIN account a ON a.account_number = d.account_number,
     generate_series(8, 10) g;

INSERT INTO transaction_analysis (analysis_key, pix_transaction_id, status_id, latency_ms)
SELECT gen_random_uuid()::text, p.id, s.id, 0
FROM pix_transaction p, analysis_status s
WHERE p.pix_id LIKE 'seed-%' AND s.enumerator = 'approved';
