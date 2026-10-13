"""Host-side custom instances; factors never become task instructions."""

import json
from pathlib import Path


def load_instance(path):
    data = json.loads(Path(path).read_text())
    values = []
    for key in ("number", "p", "q"):
        value = data[key]
        if isinstance(value, bool) or not str(value).isdigit():
            raise ValueError(f"{key} must be a positive decimal integer")
        values.append(int(value))
    number, p, q = values
    p, q = sorted((p, q))

    # Deterministic Miller–Rabin for integers below 2**64.
    def prime(n):
        if n < 2:
            return False
        for a in (2, 3, 5, 7, 11):
            if n % a == 0:
                return n == a
        d, s = n - 1, 0
        while d % 2 == 0:
            d //= 2
            s += 1
        for a in (2, 325, 9375, 28178, 450775, 9780504, 1795265022):
            if a % n == 0:
                continue
            x = pow(a, d, n)
            if x in (1, n - 1):
                continue
            for _ in range(s - 1):
                x = x * x % n
                if x == n - 1:
                    break
            else:
                return False
        return True

    if not 4 <= number.bit_length() <= 128:
        raise ValueError("Custom instances require a number of 4 to 128 bits")
    if q >= 2**64:
        raise ValueError(
            "Each prime factor must be below 2**64 for deterministic primality validation"
        )
    if p % 2 == 0 or q % 2 == 0:
        raise ValueError("Fermat instances require odd prime factors")
    if p == q or p * q != number or not prime(p) or not prime(q):
        raise ValueError("number must equal the product of two distinct primes p and q")
    return dict(number=number, p=p, q=q)


def instance_suffix(instance):
    return "__n" + str(instance["number"])
