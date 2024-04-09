###############################################################################
# (C) Copyright 2020-2024 Andrea Sorbini
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as 
# published by the Free Software Foundation, either version 3 of the 
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
###############################################################################
import subprocess
import ipaddress
from typing import Iterable
from uno.test.integration import Experiment, Host

def ping_test(experiment: Experiment, ping_config: Iterable[tuple[Host, Host, ipaddress.IPv4Address]], batch_size: int|None=None):
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

