from typing import Tuple
from hashlib import sha256

def _htdigest_hash(user: str, realm: str, password: str) -> Tuple[str, str]:
  user_hash = sha256(f"{user}:{realm}".encode("utf-8")).hexdigest()
  password_hash = sha256(f"{user}:{realm}:{password}".encode("utf-8")).hexdigest()
  return password_hash, user_hash


def htdigest_generate(user: str, realm: str, password: str) -> str:
  phash, uhash = _htdigest_hash(user, realm, password)
  return f"{user}:{realm}:{phash}:{uhash}"


def htdigest_verify(htdigest: str, user: str, realm: str, password: str) -> bool:
  ht_user, ht_realm, ht_phash, ht_uhash = htdigest.split(":")
  if ht_user != user or ht_realm != realm:
    return False
  phash, uhash = _htdigest_hash(user, realm, password)
  return phash == ht_phash and uhash == ht_uhash

