from errors import QIException


class NotFoundPixTransaction(QIException):
    code = "QIT001001"

    def __init__(self, pix_id) -> None:
        title = "Pix Transaction not Found"
        http_status = 404
        description = f"No Pix transaction with id {pix_id} was received."
        translation = f"Nenhum Pix com id {pix_id} foi recebido."
        super().__init__(title, self.code, http_status, description, translation)


class InvalidDateTime(QIException):
    """A data tem o formato certo e não existe no calendário.

    O `pattern` do schema conta dígitos, não dias: "2026-02-30T10:00:00-03:00"
    passa por ele e morre no `datetime.fromisoformat`. Sem esta classe, esse
    ValueError virava 500 — a API culpando a si mesma por um erro de quem
    chamou.
    """

    code = "QIT001002"

    def __init__(self, field, value) -> None:
        title = "Invalid Date"
        http_status = 422
        description = f"The value {value} in {field} is not a real date."
        translation = f"A data {value} em {field} não existe."
        super().__init__(title, self.code, http_status, description, translation)
