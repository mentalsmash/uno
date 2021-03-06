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
from .router import UvnRouter, logger
from .quagga import QuaggaCellHelper

class CellRouter(UvnRouter):
    def __init__(self, basedir, registry, vpn, listener, cell, cell_cfg, roaming):
        self.cell = cell
        self.cell_cfg = cell_cfg
        self.roaming = roaming
        UvnRouter.__init__(self, basedir, registry, vpn, listener)

    def _get_quagga_cls(self):
        return QuaggaCellHelper, {
            "cell": self.cell,
            "cell_cfg": self.cell_cfg,
            "roaming": self.roaming
        }
