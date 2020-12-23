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
from libuno import wg
from libuno.yml import YamlSerializer

class PresharedKeys(dict):

    @staticmethod
    def generate_key(peer_a, peer_b):
        if (peer_a > peer_b):
            return (peer_b, peer_a)
        else:
            return (peer_a, peer_b)

    def __init__(self):
        super().__init__()
    
    def assert_psk(self, peer_a, peer_b, psk = None):
        k = PresharedKeys.generate_key(peer_a, peer_b)

        psk_out = self.get(k)
        if (psk_out is None):
            if (psk is None):
                psk_out = wg.genkeypreshared()
            else:
                psk_out = psk
            self[k] = psk_out
        
        return psk_out
    
    def get_psk(self, peer_a, peer_b):
        return self[PresharedKeys.generate_key(peer_a, peer_b)]
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            psk_cells = kwargs.get("psk_cells", [])

            def exportable_key(k):
                # Ignore entry if either one of the cells is not
                # part of the selected target cells
                public_only=kwargs.get("public_only",False)
                res = (not public_only or
                        (k[0] in  psk_cells and k[1] in psk_cells))
                return res

            yml_repr = dict()
            for psk_k, psk in py_repr.items():
                if (not exportable_key(psk_k)):
                    continue
                yml_repr["{}".format(repr(psk_k))] = psk
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = PresharedKeys()
            for psk_k, psk in yml_repr.items():
                # eval() is a security risk if source Yaml is not trusted
                py_repr[eval(psk_k)] = psk
            return py_repr

