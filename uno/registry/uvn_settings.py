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

from .versioned import Versioned, prepare_enum
from .timing_profile import TimingProfile
from .vpn_settings import RootVpnSettings, ParticlesVpnSettings, BackboneVpnSettings

class UvnSettings(Versioned):
  PROPERTIES = [
    "root_vpn",
    "particles_vpn",
    "backbone_vpn",
    "timing_profile",
    "enable_particles_vpn",
    "enable_root_vpn",
    "enable_dds_security",
    "dds_domain",
  ]
  INITIAL_TIMING_PROFILE = TimingProfile.DEFAULT
  INITIAL_ENABLE_PARTICLES_VPN = True
  INITIAL_ENABLE_ROOT_VPN = True
  INITIAL_ENABLE_DDS_SECURITY = False
  INITIAL_DDS_DOMAIN = 46

  INITIAL_ROOT_VPN = lambda self: self.new_child(RootVpnSettings)
  INITIAL_PARTICLES_VPN = lambda self: self.new_child(ParticlesVpnSettings)
  INITIAL_BACKBONE_VPN = lambda self: self.new_child(BackboneVpnSettings)

  def prepare_timing_profile(self, val: str | TimingProfile) -> TimingProfile:
    return prepare_enum(self.db, TimingProfile, val)

  