
from uno.uvn.time import Timestamp

def test_basic():
  t = Timestamp.now()
  t_fmt = t.format()
  assert isinstance(t_fmt, str)
  assert len(t_fmt) > 0
  p = Timestamp.parse(t_fmt)
  assert t == p
  p_fmt = p.format()
  assert p_fmt == t_fmt

