import secrets


def generate_pickup_code(existing_codes):
    """Random 4-digit code not present in `existing_codes`."""
    taken = set(existing_codes)
    while True:
        code = f"{secrets.randbelow(10_000):04d}"
        if code not in taken:
            taken.add(code)
            return code
