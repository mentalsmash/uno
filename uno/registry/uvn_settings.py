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
from typing import Generator
from .versioned import Versioned, prepare_enum
from .timing_profile import TimingProfile
from .vpn_settings import RootVpnSettings, ParticlesVpnSettings, BackboneVpnSettings
from .deployment_strategy import DeploymentStrategyKind


class DeploymentSettings(Versioned):
  PROPERTIES = [
    "strategy",
    "strategy_args",
  ]
  INITIAL_STRATEGY = DeploymentStrategyKind.CROSSED
  EQ_PROPERTIES = [
    "strategy",
    "strategy_args",
  ]

  def prepare_strategy(self, val: str | DeploymentStrategyKind) -> DeploymentStrategyKind:
    return prepare_enum(self.db, DeploymentStrategyKind, val)

  def prepare_strategy_args(self, val: str | dict) -> dict:
    if isinstance(val, str):
      val = self.yaml_load(val)
    return val


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
    "deployment",
  ]
  EQ_PROPERTIES = PROPERTIES
  INITIAL_TIMING_PROFILE = TimingProfile.DEFAULT
  INITIAL_ENABLE_PARTICLES_VPN = True
  INITIAL_ENABLE_ROOT_VPN = True
  INITIAL_ENABLE_DDS_SECURITY = False
  INITIAL_DDS_DOMAIN = 46

  # INITIAL_ROOT_VPN = lambda self: self.new_child(RootVpnSettings)
  # INITIAL_PARTICLES_VPN = lambda self: self.new_child(ParticlesVpnSettings)
  # INITIAL_BACKBONE_VPN = lambda self: self.new_child(BackboneVpnSettings)
  # INITIAL_DEPLOYMENT = lambda self: self.new_child(DeploymentSettings)

  def load_nested(self) -> None:
    if self.root_vpn is None:
      self.root_vpn = self.new_child(RootVpnSettings)
    if self.particles_vpn is None:
      self.particles_vpn = self.new_child(ParticlesVpnSettings)
    if self.backbone_vpn is None:
      self.backbone_vpn = self.new_child(BackboneVpnSettings)
    if self.deployment is None:
      self.deployment = self.new_child(DeploymentSettings)

  def prepare_timing_profile(self, val: str | TimingProfile) -> TimingProfile:
    return prepare_enum(self.db, TimingProfile, val)

  def prepare_root_vpn(self, val: str | dict | RootVpnSettings) -> RootVpnSettings:
    return self.new_child(RootVpnSettings, val)

  def prepare_particles_vpn(self, val: str | dict | ParticlesVpnSettings) -> ParticlesVpnSettings:
    return self.new_child(ParticlesVpnSettings, val)

  def prepare_backbone_vpn(self, val: str | dict | BackboneVpnSettings) -> BackboneVpnSettings:
    return self.new_child(BackboneVpnSettings, val)

  def prepare_deployment(self, val: str | dict | DeploymentSettings) -> DeploymentSettings:
    settings = self.new_child(DeploymentSettings, val)
    return settings

  @property
  def nested(self) -> Generator[Versioned, None, None]:
    yield self.root_vpn
    yield self.particles_vpn
    yield self.backbone_vpn
    yield self.deployment
