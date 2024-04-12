class Handle:
  def __init__(self, value: object) -> None:
    self.__value = value

  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Handle):
      return False
    return self.__value == other.__value

  def __str__(self) -> str:
    return str(self.__value)

  def __repr__(self) -> str:
    return f"{self.__class__.__qualname__}({str(self)})"
