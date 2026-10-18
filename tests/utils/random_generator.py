import random
from uuid import uuid4


class RandomGenerator:
    @staticmethod
    def cpf() -> str:
        """Um CPF válido, só dígitos."""
        cpf = [random.randrange(10) for _ in range(9)]
        for _ in range(2):
            value = sum([(len(cpf) + 1 - i) * v for i, v in enumerate(cpf)]) % 11
            cpf.append(11 - value if value > 1 else 0)

        return "".join(str(digit) for digit in cpf)

    @staticmethod
    def masked_cpf(cpf: str) -> str:
        return f"{cpf[0:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:11]}"

    @staticmethod
    def cnpj() -> str:
        """Um CNPJ válido, só dígitos."""
        cnpj = [random.randrange(10) for _ in range(8)] + [0, 0, 0, 1]
        for _ in range(2):
            value = sum(v * (i % 8 + 2) for i, v in enumerate(reversed(cnpj)))
            digit = 11 - value % 11
            cnpj.append(digit if digit < 10 else 0)

        return "".join(str(digit) for digit in cnpj)

    @staticmethod
    def account_number() -> str:
        """Número de conta que nenhum outro teste vai usar."""
        return str(random.randrange(10**9, 10**10))

    @staticmethod
    def pix_id() -> str:
        return f"pix-test-{uuid4()}"
