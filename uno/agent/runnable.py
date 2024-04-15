###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from ..registry.versioned import Versioned, disabled_if


class Runnable(Versioned):
  PROPERTIES = [
    "started",
    "runnable",
  ]
  INITIAL_STARTED = False
  INITIAL_RUNNABLE = True

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    if not self.check_runnable():
      self.runnable = False

  def __enter__(self) -> "Runnable":
    self.start()
    self.started = True
    self.log.activity("started")
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.log.activity("stopping...")
    try:
      self.stop(assert_stopped=exc_type is not None and not issubclass(exc_type, KeyboardInterrupt))
    finally:
      self.started = False
    self.log.activity("stopped.")

  def check_runnable(self) -> bool:
    return True

  def configure(self, **config_args) -> set[str]:
    result = super().configure(**config_args)
    if not self.check_runnable():
      self.log.error("NOT RUNNABLE ON CONFIGURE")
      config_args["runnable"] = False
    return result

  @disabled_if("runnable", neg=True)
  def start(self) -> None:
    self._start()

  def stop(self, assert_stopped: bool) -> None:
    if assert_stopped:
      self.log.debug("asserting stopped...")
    else:
      self.log.debug("stopping services...")
    return self._stop(assert_stopped)

  @disabled_if("runnable", neg=True)
  def spin_once(self) -> None:
    self._spin_once()

  def _stop(self, assert_stopped: bool) -> None:
    raise NotImplementedError()

  def _start(self) -> None:
    raise NotImplementedError()

  def _spin_once(self) -> None:
    pass
