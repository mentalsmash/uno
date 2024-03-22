------------------------------------------------------------------------------
-- agent_configs --
-------------------------------------------------------------------------------
CREATE TABLE agent_configs (
  id INT PRIMARY KEY CHECK (id > 0),
  generation_ts CHAR(22) NOT NULL,
  init_ts CHAR(22) NOT NULL,
  owner_id TEXT,
  registry_id CHAR(64) NOT NULL CHECK(length(registry_id) == 64),
  -- deployment TEXT,
  -- root_vpn_config TEXT,
  -- particles_vpn_config TEXT,
  -- backbone_vpn_configs TEXT,
  enable_systemd BOOL DEFAULT(FALSE) NOT NULL,
  enable_router BOOL DEFAULT(FALSE) NOT NULL,
  enable_httpd BOOL DEFAULT(FALSE) NOT NULL,
  enable_peers_tester BOOL DEFAULT(FALSE) NOT NULL
  );

INSERT INTO next_id (target) VALUES ("agent_configs");

-- -------------------------------------------------------------------------------
-- -- agent_configs_uvns --
-- -------------------------------------------------------------------------------
-- CREATE TABLE agent_configs_uvns (
--   owner INT NOT NULL,
--   target INT NOT NULL,
--   owned BOOL DEFAULT(FALSE) NOT NULL,
--   PRIMARY KEY(owner, target),
--   FOREIGN KEY(owner) REFERENCES uvns(id),
--   FOREIGN KEY(target) REFERENCES agent_configs(id));


-- -------------------------------------------------------------------------------
-- -- agent_configs_cells --
-- -------------------------------------------------------------------------------
-- CREATE TABLE agent_configs_cells (
--   owner INT NOT NULL,
--   target INT NOT NULL,
--   owned BOOL DEFAULT(FALSE) NOT NULL,
--   PRIMARY KEY(owner, target),
--   FOREIGN KEY(owner) REFERENCES cells(id),
--   FOREIGN KEY(target) REFERENCES agent_configs(id));


------------------------------------------------------------------------------
-- peers --
-------------------------------------------------------------------------------
CREATE TABLE peers (
  id INT PRIMARY KEY CHECK (id > 0),
  generation_ts CHAR(22) NOT NULL,
  init_ts CHAR(22) NOT NULL,
  owner_id TEXT,
  registry_id CHAR(64) CHECK(registry_id IS NULL OR length(registry_id) == 64),
  status CHAR(255) DEFAULT('defined') NOT NULL,
  routed_networks TEXT NOT NULL,
  ts_start CHAR(22));

INSERT INTO next_id (target) VALUES ("peers");

-- -------------------------------------------------------------------------------
-- -- peers_owner_uvns --
-- -------------------------------------------------------------------------------
-- CREATE TABLE peers_owner_uvns (
--   owner INT NOT NULL,
--   target INT NOT NULL,
--   owned BOOL DEFAULT(FALSE) NOT NULL,
--   PRIMARY KEY(owner, target),
--   FOREIGN KEY(owner) REFERENCES uvns(id),
--   FOREIGN KEY(target) REFERENCES peers(id));


-- -------------------------------------------------------------------------------
-- -- peers_owner_cells --
-- -------------------------------------------------------------------------------
-- CREATE TABLE peers_owner_cells (
--   owner INT NOT NULL,
--   target INT NOT NULL,
--   owned BOOL DEFAULT(FALSE) NOT NULL,
--   PRIMARY KEY(owner, target),
--   FOREIGN KEY(owner) REFERENCES cells(id),
--   FOREIGN KEY(target) REFERENCES peers(id));


-- -------------------------------------------------------------------------------
-- -- peers_owner_particle --
-- -------------------------------------------------------------------------------
-- CREATE TABLE peers_owner_particle (
--   owner INT NOT NULL,
--   target INT NOT NULL,
--   owned BOOL DEFAULT(FALSE) NOT NULL,
--   PRIMARY KEY(owner, target),
--   FOREIGN KEY(owner) REFERENCES particles(id),
--   FOREIGN KEY(target) REFERENCES peers(id));


------------------------------------------------------------------------------
-- peers_vpn_status --
-------------------------------------------------------------------------------
CREATE TABLE peers_vpn_status (
  id INT PRIMARY KEY CHECK (id > 0),
  generation_ts CHAR(22) NOT NULL,
  intf CHAR(15) NOT NULL,
  online BOOL DEFAULT(FALSE) NOT NULL,
  peer INT NOT NULL,
  FOREIGN KEY(peer) REFERENCES peers(id));

INSERT INTO next_id (target) VALUES ("peers_vpn_status");

------------------------------------------------------------------------------
-- peers_lan_status --
-------------------------------------------------------------------------------
CREATE TABLE peers_lan_status (
  id INT PRIMARY KEY CHECK (id > 0),
  generation_ts CHAR(22) NOT NULL,
  lan TEXT NOT NULL UNIQUE,
  reachable BOOL DEFAULT(FALSE) NOT NULL,
  peer INT NOT NULL,
  FOREIGN KEY(peer) REFERENCES peers(id));

INSERT INTO next_id (target) VALUES ("peers_lan_status");
