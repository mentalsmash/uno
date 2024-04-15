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
import subprocess
import ipaddress
from typing import Iterable
from uno.test.integration import Experiment, Host


def ping_test(
  experiment: Experiment,
  ping_config: Iterable[tuple[Host, Host, ipaddress.IPv4Address]],
  batch_size: int | None = None,
):
  ping_count = 3
  ping_max_wait = 10
  if batch_size is None:
    batch_size = len(experiment.networks)

  # Start tests in batches using popen, then wait for them to terminate
  def _wait_batch(batch: list[tuple[Host, Host, ipaddress.IPv4Address, subprocess.Popen]]):
    for host, other_host, address, test in batch:
      rc = test.wait(ping_max_wait)
      assert rc == 0, f"PING FAILED {host} → {other_host}@{address}"
      experiment.log.info("PING OK {} → {}@{}", host, other_host, address)

  batch = []
  for host, other_host, address in ping_config:
    if len(batch) == batch_size:
      _wait_batch(batch)
      batch = []
    experiment.log.activity("PING START {} → {}@{}", host, other_host, address)
    test = host.popen("ping", "-c", f"{ping_count}", str(address))
    batch.append((host, other_host, address, test))
  if batch:
    _wait_batch(batch)
    batch = []
