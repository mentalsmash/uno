from hashlib import sha256


def _htdigest_hash(
  user: str, realm: str, password: str | None = None, password_hash: str | None = None
) -> tuple[str, str]:
  user_hash = sha256(f"{user}:{realm}".encode("utf-8")).hexdigest()
  if password_hash is None:
    password_hash = sha256(f"{user}:{realm}:{password}".encode("utf-8")).hexdigest()
  return password_hash, user_hash


def htdigest_generate(
  user: str, realm: str, password: str | None = None, password_hash: str | None = None
) -> str:
  if password is None and password_hash is None:
    raise ValueError("either password or password_hash must be specified")
  phash, uhash = _htdigest_hash(user, realm, password=password, password_hash=password_hash)
  return f"{user}:{realm}:{phash}:{uhash}"


def htdigest_verify(htdigest: str, user: str, realm: str, password: str) -> bool:
  ht_user, ht_realm, ht_phash, ht_uhash = htdigest.split(":")
  if ht_user != user or ht_realm != realm:
    return False
  phash, uhash = _htdigest_hash(user, realm, password)
  return phash == ht_phash and uhash == ht_uhash
