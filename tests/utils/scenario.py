"""Monta o cenário de um teste direto no banco.

No Base Service os testes criam tudo pela API. Aqui não dá: onboarding
(cadastro de cliente e conta) está fora do escopo do desafio, então não
existe rota que crie uma conta. Clientes, contas, bloqueios e extrato
antigo nascem por SQL — e o Pix, que é o que está sendo testado, continua
entrando pela API.

Cada conta criada aqui tem número aleatório: os testes não se esbarram e
nenhum precisa apagar o banco.
"""

from datetime import datetime, timedelta, timezone
from os import environ
from typing import Optional
from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils.random_generator import RandomGenerator

DEFAULT_DATABASE_URL = "postgresql+psycopg2://pix:pix@localhost:5432/pix_antifraude"

OUR_ISPB = "88888888"
SAO_PAULO = timezone(timedelta(hours=-3))

_engine = None


def engine():
    global _engine

    if _engine is None:
        _engine = create_engine(environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), pool_pre_ping=True)

    return _engine


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class Scenario:
    @staticmethod
    def internal_account(
        balance: int = 500000,
        daily_limit: int = 1000000,
        nightly_limit: int = 100000,
        opening_date: Optional[datetime] = None,
        birth_date: str = "1990-01-01",
        document_number: Optional[str] = None,
        registered_device: bool = True,
    ) -> dict:
        """Um cliente nosso com uma conta. Devolve o que o payload precisa.

        Cada conta tem o próprio aparelho (`device_id`), que o PayloadGenerator
        usa por padrão. Com `registered_device`, o aparelho já é cadastrado
        (IN BCB 491: Pix aprovado em 3 dias distintos, o primeiro há 7+ dias),
        como o de um cliente comum; sem ele, é um aparelho que nunca fez Pix.
        """
        if document_number is None:
            document_number = RandomGenerator.cpf()

        if opening_date is None:
            opening_date = datetime.now(SAO_PAULO) - timedelta(days=400)

        account_number = RandomGenerator.account_number()

        with engine().begin() as connection:
            customer_id = connection.execute(
                text(
                    "INSERT INTO customer (customer_key, document_number, name, birth_date) "
                    "VALUES (:key, :document, :name, :birth_date) RETURNING id"
                ),
                {
                    "key": str(uuid4()),
                    "document": document_number,
                    "name": "Cliente de Teste",
                    "birth_date": birth_date,
                },
            ).scalar()

            account_id = connection.execute(
                text(
                    "INSERT INTO account (account_key, customer_id, branch, account_number, opening_date, balance, "
                    "daily_limit, nightly_limit) "
                    "VALUES (:key, :customer_id, '0001', :number, :opening_date, :balance, :daily, :nightly) RETURNING id"
                ),
                {
                    "key": str(uuid4()),
                    "customer_id": customer_id,
                    "number": account_number,
                    "opening_date": opening_date,
                    "balance": balance,
                    "daily": daily_limit,
                    "nightly": nightly_limit,
                },
            ).scalar()

        account = {
            "account_id": account_id,
            "participant": OUR_ISPB,
            "branch": "0001",
            "account_number": account_number,
            "document_number": document_number,
            "opening_date": iso(opening_date),
            "device_id": f"dvc-{account_number}",
        }

        if registered_device:
            Scenario.register_device(account, account["device_id"])

        return account

    @staticmethod
    def register_device(account: dict, device_id: str, days_ago: tuple = (30, 25, 20)) -> None:
        """Pix pequenos e aprovados deste aparelho, em dias distintos: o aparelho vira cadastrado.

        O destino é uma conta de outro banco só deste histórico, para não
        mexer no histórico de nenhum destino dos testes.
        """
        sink = Scenario.external_account()
        now = datetime.now(SAO_PAULO)

        with engine().begin() as connection:
            status_id = connection.execute(
                text("SELECT id FROM analysis_status WHERE enumerator = 'approved'")
            ).scalar()

            for days in days_ago:
                pix_id = connection.execute(
                    text(
                        "INSERT INTO pix_transaction (pix_id, amount, transaction_date, source_account_id, "
                        "destination_participant, destination_branch, destination_account_number, "
                        "destination_opening_date, destination_document_number, device_id, channel, ip, payload) "
                        "VALUES (:pix_id, 1000, :moment, :account_id, :participant, :branch, :number, "
                        ":opening_date, :document, :device_id, 'app', '198.51.100.23', '{}'::jsonb) RETURNING id"
                    ),
                    {
                        "pix_id": RandomGenerator.pix_id(),
                        "moment": now - timedelta(days=days),
                        "account_id": account["account_id"],
                        "participant": sink["participant"],
                        "branch": sink["branch"],
                        "number": sink["account_number"],
                        "opening_date": sink["opening_date"],
                        "document": sink["document_number"],
                        "device_id": device_id,
                    },
                ).scalar()

                connection.execute(
                    text(
                        "INSERT INTO transaction_analysis (analysis_key, pix_transaction_id, status_id, latency_ms) "
                        "VALUES (:key, :pix_id, :status_id, 0)"
                    ),
                    {"key": str(uuid4()), "pix_id": pix_id, "status_id": status_id},
                )

    @staticmethod
    def restricted(document_number: str, list_name: str) -> None:
        """Põe um CPF/CNPJ numa lista restritiva (csnu, bets, court_order)."""
        with engine().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO restricted_party (document_number, list, reason, listed_at) "
                    "VALUES (:document, :list, 'teste', CURRENT_DATE) ON CONFLICT DO NOTHING"
                ),
                {"document": document_number, "list": list_name},
            )

    @staticmethod
    def decision(pix_id: str) -> dict:
        """A camada interna da análise (sinais, P, ρ, ameaça, PLD)."""
        with engine().connect() as connection:
            return connection.execute(
                text(
                    "SELECT a.decision FROM transaction_analysis a JOIN pix_transaction p "
                    "ON p.id = a.pix_transaction_id WHERE p.pix_id = :pix_id"
                ),
                {"pix_id": pix_id},
            ).scalar()

    @staticmethod
    def external_account(
        participant: str = "60701190",
        opening_date: Optional[datetime] = None,
        document_number: Optional[str] = None,
    ) -> dict:
        """Uma conta de outro banco: só existe no payload, não no nosso banco."""
        if opening_date is None:
            opening_date = datetime.now(SAO_PAULO) - timedelta(days=900)

        if document_number is None:
            document_number = RandomGenerator.cpf()

        return {
            "participant": participant,
            "branch": "0001",
            "account_number": RandomGenerator.account_number(),
            "document_number": document_number,
            "opening_date": iso(opening_date),
        }

    @staticmethod
    def statement(account: dict, direction: str, amount: int, occurred_at: datetime, counterparty: dict = None) -> None:
        """Uma linha de extrato antiga, como as que vêm do seed."""
        if counterparty is None:
            counterparty = Scenario.external_account()

        with engine().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_statement (account_id, direction, amount, counterparty_participant, "
                    "counterparty_branch, counterparty_account_number, counterparty_document, occurred_at) "
                    "VALUES (:account_id, :direction, :amount, :participant, :branch, :number, :document, :occurred_at)"
                ),
                {
                    "account_id": account["account_id"],
                    "direction": direction,
                    "amount": amount,
                    "participant": counterparty["participant"],
                    "branch": counterparty["branch"],
                    "number": counterparty["account_number"],
                    "document": counterparty["document_number"],
                    "occurred_at": occurred_at,
                },
            )

    @staticmethod
    def block(account: dict, started_at: datetime, ended_at: Optional[datetime] = None) -> None:
        with engine().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account_block (account_id, reason, started_at, ended_at) "
                    "VALUES (:account_id, 'teste', :started_at, :ended_at)"
                ),
                {"account_id": account["account_id"], "started_at": started_at, "ended_at": ended_at},
            )

    @staticmethod
    def balance(account: dict) -> int:
        with engine().connect() as connection:
            return connection.execute(
                text("SELECT balance FROM account WHERE id = :id"), {"id": account["account_id"]}
            ).scalar()

    @staticmethod
    def statements_from_pix(account: dict) -> list:
        """As linhas de extrato que a API criou (as que têm Pix)."""
        with engine().connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT direction, amount, counterparty_participant, counterparty_branch, "
                    "counterparty_account_number, counterparty_document "
                    "FROM account_statement WHERE account_id = :id AND pix_transaction_id IS NOT NULL ORDER BY id"
                ),
                {"id": account["account_id"]},
            ).mappings().all()

        return [dict(row) for row in rows]

    @staticmethod
    def analysis(pix_id: str) -> dict:
        """A análise gravada, com o que o motor viu."""
        with engine().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT s.enumerator AS status, a.features, a.dict_response, a.dict_fetched_at, a.latency_ms, "
                    "p.source_account_id, p.destination_account_id "
                    "FROM transaction_analysis a "
                    "JOIN pix_transaction p ON p.id = a.pix_transaction_id "
                    "JOIN analysis_status s ON s.id = a.status_id "
                    "WHERE p.pix_id = :pix_id"
                ),
                {"pix_id": pix_id},
            ).mappings().first()

        return dict(row) if row is not None else None

    @staticmethod
    def baselines(account: dict) -> list:
        with engine().connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM account_baseline WHERE account_id = :id ORDER BY baseline_date"),
                {"id": account["account_id"]},
            ).mappings().all()

        return [dict(row) for row in rows]
