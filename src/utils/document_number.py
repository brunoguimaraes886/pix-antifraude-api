CPF_LENGTH = 11
CNPJ_LENGTH = 14

PERSON = "PF"
COMPANY = "PJ"


def only_digits(document_number: str) -> str:
    """O documento sem máscara: "123.456.789-09" vira "12345678909".

    O payload aceita CPF/CNPJ com ou sem máscara; o banco guarda só os
    dígitos, pra que "123.456.789-09" e "12345678909" sejam a mesma pessoa
    em qualquer comparação.
    """
    digits = []
    for character in document_number:
        if character.isdigit():
            digits.append(character)

    return "".join(digits)


def document_type(document_number: str) -> str:
    """PF ou PJ, pelo tamanho: 11 dígitos é CPF, 14 é CNPJ."""
    if len(only_digits(document_number)) == CNPJ_LENGTH:
        return COMPANY

    return PERSON
