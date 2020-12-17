###############################################################################
# (C) Copyright 2020 Andrea Sorbini
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
from libuno.exception import UvnException

import libuno.log
logger = libuno.log.logger("uvn.gw")

class UvnGateway:
    def __init__(self, registry):
        if registry.packaged:
            raise UvnException("gateway must be run on root registry")
        
        self.registry = registry
    
    def start(self, nameserver=False):
        wait_for_sigint(tgt=self, logger=logger)
    
    def stop(self):
        pass
