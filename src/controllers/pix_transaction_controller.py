import time
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from constants import OUR_ISPB
from controllers.base_controller import BaseController
from controllers.baseline_controller import BaselineController
from controllers.dict_controller import DictController
from controllers.feature_controller import FeatureController
from controllers.manual_release_controller import ManualReleaseController
from dtos import PixTransactionDTO
from engine import EngineResult, Features, get_engine
from engine.base import DictConsult
from engine.features import DICT_OK, DictFeatures
from engine.reasons import (
    ACCOUNT_BLOCKED,
    ACCOUNT_OWNER_MISMATCH,
    DESTINATION_OWNER_MISMATCH,
    ENGINE_ERROR,
    INSUFFICIENT_BALANCE,
    UNKNOWN_ACCOUNT,
    UNKNOWN_DESTINATION_ACCOUNT,
    Reason,
)
from engine.result import STATUSES
from errors import InvalidDateTime, NotFoundPixTransaction
from models import Account, AccountStatement, AnalysisStatus, PixTransaction, TransactionAnalysis
from repositories import (
    AccountBlockRepository,
    AccountRepository,
    AccountStatementRepository,
    PixTransactionRepository,
    TransactionAnalysisRepository,
)
from utils.document_number import only_digits


class PixTransactionController(BaseController):
    """O caminho de um Pix, da chegada à decisão gravada.

        1. já recebido?          → devolve a análise gravada (idempotente)
        2. trava as contas       → saldo e limite lidos sem corrida
        3. grava o Pix           → tudo que chega fica no banco
        4. conferências          → recusas operacionais, antes do motor
        5. resumo diário         → calcula no primeiro Pix do dia da conta
        6. features              → tudo que o motor vai ver, menos o DICT
        7. motor                 → regras duras; se passar, DICT (ou fallback) e o resto
        8. liberação manual      → barrado por suspeita e liberado? aprova
        9. grava a análise       → status, motivos, latência, features
       10. aprovado? movimenta   → saldo e extrato, só no approved
       11. commit

    O commit é a última linha: uma exceção em qualquer passo desfaz tudo,
    inclusive o Pix gravado no passo 3.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.account_block_repository = AccountBlockRepository(self.context)
        self.account_statement_repository = AccountStatementRepository(self.context)
        self.pix_transaction_repository = PixTransactionRepository(self.context)
        self.transaction_analysis_repository = TransactionAnalysisRepository(self.context)

    def create(self, payload: dict) -> Tuple[dict, bool]:
        """Analisa um Pix. Devolve a resposta e se a análise é nova.

        O segundo valor existe pro resource escolher o status HTTP: 201 para
        a análise feita agora, 200 para a que já existia.
        """
        started_at = time.perf_counter()
        pix_id = payload["id"]

        existing = self.pix_transaction_repository.get_by_pix_id(pix_id)
        if existing is not None:
            self.logger.info(f"Pix {pix_id} já recebido: devolvendo a análise gravada")
            return PixTransactionDTO.analysis_to_dict(existing.analysis), False

        moment = self._parse_datetime("transaction_date", payload["transaction_date"])
        destination_opening_date = self._parse_datetime(
            "destination_account.opening_date", payload["destination_account"]["opening_date"], moment
        )
        self._parse_datetime("source_account.opening_date", payload["source_account"]["opening_date"], moment)

        source_data = payload["source_account"]
        destination_data = payload["destination_account"]
        destination_is_internal = destination_data["participant"] == OUR_ISPB

        payer = self.account_repository.get_by_branch_and_number(source_data["branch"], source_data["account_number"])

        destination_account = None
        if destination_is_internal:
            destination_account = self.account_repository.get_by_branch_and_number(
                destination_data["branch"], destination_data["account_number"]
            )

        self.account_repository.lock([account for account in (payer, destination_account) if account is not None])

        # Enquanto esperava a trava, outro pedido com o mesmo id pode ter
        # terminado. Agora ele está visível.
        existing = self.pix_transaction_repository.get_by_pix_id(pix_id)
        if existing is not None:
            return PixTransactionDTO.analysis_to_dict(existing.analysis), False

        pix = self.pix_transaction_repository.create(
            payload, moment, destination_opening_date, payer, destination_account
        )

        try:
            self.session.flush()
        except IntegrityError:
            # Dois pedidos com o mesmo id e pagador desconhecido (sem conta
            # pra travar): o segundo bate no UNIQUE(pix_id) e devolve o
            # que o primeiro gravou.
            self.session.rollback()
            existing = self.pix_transaction_repository.get_by_pix_id(pix_id)
            return PixTransactionDTO.analysis_to_dict(existing.analysis), False

        operational_reasons = self._operational_reasons(payload, moment, payer, destination_is_internal, destination_account)

        if operational_reasons:
            analysis = self._save_analysis(pix, AnalysisStatus.REJECTED, operational_reasons, started_at)
            return self._commit(analysis), True

        baseline_controller = BaselineController()
        payer_baseline = baseline_controller.get_or_create(payer, moment)

        destination_baseline = None
        if destination_account is not None:
            destination_baseline = baseline_controller.get_or_create(destination_account, moment)

        features = FeatureController().build(
            pix, moment, payer, payer_baseline, destination_account, destination_baseline
        )

        # O motor decide se e quando consultar o DICT (depois das regras
        # duras); a resposta volta em features.destination.dict.
        result = self._evaluate(features, lambda: DictController().consult(pix))

        released = ManualReleaseController().apply(pix, result)
        if released is not None:
            result = released

        analysis = self._save_analysis(
            pix, result.status, result.reasons, started_at, result.score, features, features.destination.dict
        )

        if result.status == AnalysisStatus.APPROVED:
            self._settle(pix, moment, payer, destination_account)

        return self._commit(analysis), True

    def get_by_pix_id(self, pix_id: str) -> dict:
        pix = self.pix_transaction_repository.get_by_pix_id(pix_id)

        if pix is None:
            raise NotFoundPixTransaction(pix_id)

        return PixTransactionDTO.analysis_to_detail_dict(pix.analysis)

    # ────────────────────────────────────────────────────────────────
    # Conferências operacionais
    # ────────────────────────────────────────────────────────────────

    def _operational_reasons(
        self,
        payload: dict,
        moment: datetime,
        payer: Optional[Account],
        destination_is_internal: bool,
        destination_account: Optional[Account],
    ) -> List[Reason]:
        """O que impede o Pix de sair do jeito que veio, antes de qualquer risco.

        Não é antifraude: é o Pix que não tem como acontecer. Por isso não
        passa pelo motor e não conta como "Pix bloqueado" no resumo diário.

        Pagador desconhecido (ou com outro titular) para tudo aqui: sem a
        conta não há o que conferir. As outras conferências se somam —
        conta bloqueada E sem saldo são dois motivos.
        """
        if payer is None:
            return [UNKNOWN_ACCOUNT]

        source_document = only_digits(payload["source_account"]["owner"]["document_number"])
        if payer.customer.document_number != source_document:
            return [ACCOUNT_OWNER_MISMATCH]

        reasons = []

        if destination_is_internal:
            destination_document = only_digits(payload["destination_account"]["owner"]["document_number"])

            if destination_account is None:
                reasons.append(UNKNOWN_DESTINATION_ACCOUNT)
            elif destination_account.customer.document_number != destination_document:
                reasons.append(DESTINATION_OWNER_MISMATCH)

        if self.account_block_repository.is_blocked(payer.id, moment):
            reasons.append(ACCOUNT_BLOCKED)

        if payer.balance < payload["amount"]:
            reasons.append(INSUFFICIENT_BALANCE)

        return reasons

    # ────────────────────────────────────────────────────────────────
    # O motor
    # ────────────────────────────────────────────────────────────────

    def _evaluate(self, features: Features, consult_dict: DictConsult) -> EngineResult:
        """Chama o motor — e não deixa um motor quebrado decidir sozinho.

        Se o motor levantar exceção ou devolver um status que não existe, o
        Pix não é aprovado às cegas nem vira 500: pede 2FA, com o motivo
        `engine_error`, e o erro vai pro log com a pilha inteira.
        """
        try:
            result = get_engine().evaluate(features, consult_dict)
        except Exception:
            self.logger.exception(f"O motor falhou no Pix {features.transaction.pix_id}")
            return EngineResult(status=AnalysisStatus.TWO_FACTOR_REQUIRED, reasons=[ENGINE_ERROR])

        if result is None or result.status not in STATUSES:
            self.logger.error(f"O motor devolveu um resultado inválido no Pix {features.transaction.pix_id}: {result}")
            return EngineResult(status=AnalysisStatus.TWO_FACTOR_REQUIRED, reasons=[ENGINE_ERROR])

        # Contrato da resposta: no approved, a lista de motivos vem vazia.
        if result.status == AnalysisStatus.APPROVED:
            result.reasons = []

        return result

    # ────────────────────────────────────────────────────────────────
    # Gravação
    # ────────────────────────────────────────────────────────────────

    def _save_analysis(
        self,
        pix: PixTransaction,
        status: str,
        reasons: List[Reason],
        started_at: float,
        score: Optional[float] = None,
        features: Optional[Features] = None,
        dict_features: Optional[DictFeatures] = None,
    ) -> TransactionAnalysis:
        """Grava a decisão. A latência é medida aqui: do pedido até a decisão."""
        dict_response = None
        dict_fetched_at = None

        if dict_features is not None and dict_features.status == DICT_OK:
            dict_response = dict_features.response
            dict_fetched_at = dict_features.fetched_at

        latency_ms = int((time.perf_counter() - started_at) * 1000)

        self.logger.info(f"Pix {pix.pix_id}: {status} {[reason.code for reason in reasons]} em {latency_ms} ms")

        return self.transaction_analysis_repository.create(
            pix=pix,
            status_enumerator=status,
            reasons=reasons,
            latency_ms=latency_ms,
            score=score,
            features=features.to_dict() if features is not None else None,
            dict_response=dict_response,
            dict_fetched_at=dict_fetched_at,
        )

    def _settle(
        self, pix: PixTransaction, moment: datetime, payer: Account, destination_account: Optional[Account]
    ) -> None:
        """Move o dinheiro: só o Pix aprovado chega aqui.

        Saída no extrato do pagador; se o destino é conta nossa, entrada no
        extrato dela. 2FA não movimenta: sem retorno da confirmação, o Pix
        é tratado como não executado (mas conta como tentativa).
        """
        self.account_repository.debit(payer, pix.amount)
        self.account_statement_repository.create(
            account_id=payer.id,
            direction=AccountStatement.OUT,
            amount=pix.amount,
            counterparty={
                "participant": pix.destination_participant,
                "branch": pix.destination_branch,
                "account_number": pix.destination_account_number,
                "document_number": pix.destination_document_number,
            },
            occurred_at=moment,
            pix_transaction_id=pix.id,
        )

        if destination_account is None:
            return

        self.account_repository.credit(destination_account, pix.amount)
        self.account_statement_repository.create(
            account_id=destination_account.id,
            direction=AccountStatement.IN,
            amount=pix.amount,
            counterparty={
                "participant": OUR_ISPB,
                "branch": payer.branch,
                "account_number": payer.account_number,
                "document_number": payer.customer.document_number,
            },
            occurred_at=moment,
            pix_transaction_id=pix.id,
        )

    def _commit(self, analysis: TransactionAnalysis) -> dict:
        analysis_dto = PixTransactionDTO.analysis_to_dict(analysis)
        self.session.commit()

        return analysis_dto

    def _parse_datetime(self, field: str, raw_value: str, reference: Optional[datetime] = None) -> datetime:
        """Converte a data, ou recusa com 422 em vez de 500.

        O schema garante o FORMATO; o calendário (30 de fevereiro) só se
        descobre aqui. Data sem hora (permitida nos opening_date) vira
        meia-noite no fuso da transação.
        """
        try:
            value = datetime.fromisoformat(raw_value)
        except ValueError:
            raise InvalidDateTime(field, raw_value)

        if value.tzinfo is None:
            if reference is None:
                raise InvalidDateTime(field, raw_value)
            value = value.replace(tzinfo=reference.tzinfo)

        return value
