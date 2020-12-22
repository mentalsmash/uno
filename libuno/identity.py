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
"""Helper module to manipulate a database of identities"""

import gnupg
import pathlib
import os
import secrets
import tempfile
import shutil
import subprocess

import libuno

from libuno.cfg import UvnDefaults
from libuno.yml import YamlSerializer, repr_yml, repr_py, yml_obj, yml
from libuno.exec import exec_command
from libuno.exception import UvnException

logger = libuno.log.logger("uvn.db")

class PackagedDescriptor:
    def __get__(self, obj, objtype=None):
        return obj.pkg_cell is not None

def DisabledIfPackaged(fn):
    def _wrapper(self, *args, **kwargs):
        if self.packaged:
            raise UvnException(f"operation not allowed when packaged")
        return fn(self, *args, **kwargs)
    return _wrapper

def lookup_from_env_or_file(what, env_var, value_file):
    # Lookup value from environment variable, or try to load it from a file
    # if variable is not set
    value = os.environ.get(env_var)
    if value is None:
        value_file = pathlib.Path(value_file)
        if value_file.exists():
            with value_file.open("r") as f:
                value = f.read()
                logger.trace("loaded {} from file: {}", what, value_file)
        else:
            logger.trace("value not found: {} (env={}, file={})",
                what, env_var, value_file)
    else:
        logger.trace("loaded {} from env: {}", what, env_var)
    return value

class IdentityError(Exception):
    
    def __init__(self, msg):
        self.msg = msg

class CryptoError(Exception):
    
    def __init__(self, msg):
        self.msg = msg

class GpgKey:
    def __init__(self, fingerprint, public="", private=""):
        self.fingerprint = fingerprint
        self.public = public
        self.private = private

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            return py_repr.fingerprint
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = GpgKey(fingerprint=yml_repr)
            return py_repr

class GpgKeyInfo:
    TYPE_ROOT = "root"
    TYPE_CELL = "cell"
    TYPE_PARTICLE = "particle"

    def __init__(self, key_type, owner, target):
        self.owner = owner
        self.key_type = key_type
        self.target = target
        if (self.key_type != GpgKeyInfo.TYPE_ROOT and
            self.key_type != GpgKeyInfo.TYPE_CELL and
            self.key_type != GpgKeyInfo.TYPE_PARTICLE):
            raise ValueError("unknown key type: {}".format(self.key_type))
        if not self.owner:
            raise ValueError("invalid key owner: {}".format(self.owner))
        if not self.target:
            raise ValueError("invalid key target: {}".format(self.owner))
    
    def __str__(self):
        return repr(self)

    def __repr__(self):
        return yml(self, _json=True)
    
    def __eq__(self, other):
        if not isinstance(other, GpgKeyInfo):
            return False
        return (self.owner == other.owner and
                self.key_type == other.key_type and
                self.target == other.target)
    
    @staticmethod
    def parse(key_desc):
        key_info_start = key_desc.find("(")
        if key_info_start < 0:
            raise ValueError("invalid key description: '{}'", key_desc)
        # skip "("
        key_info_start += 1
        key_info_end = key_desc.rfind(")")
        if key_info_end < 0:
            raise ValueError("invalid key description: '{}'", key_desc)
        if key_info_start >= key_info_end:
            raise ValueError("invalid key description: '{}'", key_desc)
        repr_str = key_desc[key_info_start:key_info_end]
        key_info = yml_obj(GpgKeyInfo, repr_str)
        return key_info
    
    @staticmethod
    def cell_key(cell_admin, cell_name):
        return GpgKeyInfo(GpgKeyInfo.TYPE_CELL, cell_admin, cell_name)
    
    @staticmethod
    def uvn_key(uvn_admin, uvn_address):
        return GpgKeyInfo(GpgKeyInfo.TYPE_ROOT, uvn_admin, uvn_address)
    
    @staticmethod
    def particle_key(particle_admin, particle_address):
        return GpgKeyInfo(GpgKeyInfo.TYPE_PARTICLE, particle_admin, particle_address)
    
    @staticmethod
    def match(key_desc, owner=None, target=None, key_type=None):
        try:
            key_info = GpgKeyInfo.parse(key_desc)
        except Exception as e:
            logger.debug("[exception] {}", e)
            logger.debug("failed to parse description as key info: '{}'", key_desc)
            return False
        return not ((key_type is not None and key_info.owner != owner) or
                    (owner is not None and key_info.owner != owner) or
                    (target is not None and key_info.target != target))

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["owner"] = py_repr.owner
            yml_repr["key_type"] = py_repr.key_type
            yml_repr["target"] = py_repr.target
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = GpgKeyInfo(
                        owner=yml_repr["owner"],
                        key_type=yml_repr["key_type"],
                        target=yml_repr["target"])
            return py_repr

class UvnRegistryIdentity:

    def __init__(self,
                 admin,
                 admin_name,
                 address,
                 basedir,
                 key):
        self.admin = admin
        self.admin_name = admin_name
        self.address = address
        self.basedir = pathlib.Path(basedir)
        self.key = key

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["admin"] = py_repr.admin
            yml_repr["admin_name"] = py_repr.admin_name
            yml_repr["address"] = py_repr.address
            yml_repr["key"] = repr_yml(py_repr.key, **kwargs)
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = UvnRegistryIdentity(
                            address=yml_repr["address"],
                            admin=yml_repr["admin"],
                            admin_name=yml_repr["admin_name"],
                            basedir=kwargs["basedir"],
                            key=repr_py(GpgKey, yml_repr["key"], **kwargs))
            return py_repr

class UvnCellRecord:

    def __init__(self, name, admin, address, key):
        self.name = name
        self.admin = admin
        self.address = address
        self.key = key
    
    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["name"] = py_repr.name
            yml_repr["admin"] = py_repr.admin
            yml_repr["address"] = py_repr.address
            yml_repr["key"] = repr_yml(py_repr.key, public_only=True)
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = UvnCellRecord(
                        name=yml_repr["name"],
                        admin=yml_repr["admin"],
                        address=yml_repr["address"],
                        key=repr_py(GpgKey, yml_repr["key"], **kwargs))
            return py_repr

class UvnIdentityDatabase:

    packaged = PackagedDescriptor()

    def __init__(self,
                 cell_db=False,
                 pkg_cell=None,
                 cell_key=None,
                 cell_admin=None,
                 cell_address=None,
                 admin=None,
                 admin_name=None,
                 address=None,
                 basedir=None,
                 registry_id=None,
                 loaded=False,
                 data_dir_rel=UvnDefaults["identity_db"]["path"],
                 key_length=UvnDefaults["identity_db"]["key_length"],
                 key_algo=UvnDefaults["identity_db"]["key_algo"],
                 key_encoding=UvnDefaults["identity_db"]["key_encoding"],
                 key_server=UvnDefaults["identity_db"]["key_server"],
                 **kwargs):
        
        if registry_id is None:
            if address is None:
                raise ValueError("no address specified for UVN")
            
            if admin is None:
                admin = "{}@{}".format(
                                UvnDefaults["registry"]["admin"],
                                address)
            
            if admin_name is None:
                admin_name = UvnDefaults["registry"]["admin_name"]
        

        self.loaded = loaded
        self.dirty = False

        self._auto_secrets = {}

        self.cells = {}

        self.key_length = key_length
        self.key_algo = key_algo
        self.key_encoding = key_encoding
        self.key_server = key_server

        if registry_id is None:
            self.data_dir = (pathlib.Path(basedir) / data_dir_rel).resolve()
        else:
            self.data_dir = (pathlib.Path(registry_id.basedir) / data_dir_rel).resolve()

        self.data_dir_rel = pathlib.Path(data_dir_rel)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Only set when packaged for a cell
        self.pkg_cell = pkg_cell
        self.cell_db = cell_db
        self.cell_key = cell_key
        self.cell_admin = cell_admin
        self.cell_address = cell_address

        # Initialize PGP database
        self.gpg = gnupg.GPG(gnupghome=str(self.data_dir))
        self.gpg.encoding = self.key_encoding
        
        # Initialize database, login with private key
        self.registry_id = self._initialize_registry_id(
                                admin=admin,
                                admin_name=admin_name,
                                address=address,
                                basedir=basedir,
                                registry_id=registry_id)

    def get_cell_record(self, name):
        return self.cells[name]

    @staticmethod
    def contains_db(basedir,
                    persist_file=UvnDefaults["identity_db"]["persist_file"],
                    data_dir_rel=UvnDefaults["identity_db"]["path"]):
        db_file_path = basedir / persist_file
        keys_dir_path = basedir / data_dir_rel
        return (db_file_path.exists() or keys_dir_path.exists())

    def _secret(self, admin=None, required=True):
        secret = UvnIdentityDatabase.load_secret()
        if secret is None:
            admin = admin
            if admin is None:
                if hasattr(self, "registry_id"):
                    admin = self.registry_id.admin
                elif required:
                    raise CryptoError("no master secret specified")
            return self._auto_secrets.get(admin , "")
        return secret

    @staticmethod
    def load_secret():
        secret_file = pathlib.Path(UvnDefaults["identity_db"]["secret_file"])
        secret_env = UvnDefaults["identity_db"]["secret_env"]
        return lookup_from_env_or_file("master secret", secret_env, secret_file)

    @staticmethod
    def load_secret_cell(name):
        secret_file_name = UvnDefaults["identity_db"]["cell_secret_file_fmt"].format(name)
        secret_env = UvnDefaults["identity_db"]["cell_secret_env_fmt"].format(name)
        secret_file = pathlib.Path(secret_file_name)
        return lookup_from_env_or_file("cell secret", secret_env, secret_file)

    def _secret_cell(self, name, admin):
        secret = UvnIdentityDatabase.load_secret_cell(name)
        if secret is None:
            return self._auto_secrets.get(admin, "")
        return secret
    
    def _secret_random(self, admin):
        if admin not in self._auto_secrets:
            self._auto_secrets[admin] = secrets.token_urlsafe(
                        UvnDefaults["identity_db"]["secret_len"])
            logger.debug("automatic secret: [{}, {}]",
                admin, self._auto_secrets[admin])
        return self._auto_secrets[admin]

    @staticmethod
    def _lookup_key_info(gpg, owner, target, key_type, fingerp=None):
        keys = gpg.list_keys(keys=owner)
        def filter_key(k):
            if not ("uids" in k or k["uids"]):
                # No description field found, ignore key
                return False
            if len(k["uids"]) > 1:
                logger.warning("ignoring extra UIDs for {}'s key: {}",
                    owner, k["uids"][1:])
            return GpgKeyInfo.match(k["uids"][0], owner, target, key_type)
        fkeys = [k for k in keys if filter_key(k)]
        keys_len = len(fkeys)
        if keys_len == 0:
            return None
        elif keys_len > 1:
            raise IdentityError("multiple keys found for {}".format(owner))
        if fkeys[0]["trust"] != "u" and fkeys[0]["trust"] != "f":
            logger.debug("insufficient trust in key: {}", fkeys[0])
        return fkeys[0]
    
    @staticmethod
    def _lookup_key_address(gpg, fingerprint):
        keys = gpg.list_keys(keys=fingerprint)
        keys_len = len(keys)
        expected_keys = 1
        # if with_secret:
        #     expected_keys += 1
        if keys_len == 0:
            return None
        elif keys_len > expected_keys:
            raise IdentityError("multiple keys found for {}".format(fingerprint))
        if len(keys[0]["uids"]) == 0:
            raise IdentityError("no uids associated with key {}".format(fingerprint))
        return keys[0]["uids"][0].split("<")[1].split(">")[0]

    @staticmethod
    def _load_key(gpg, owner, target, key_type, with_secret=False, passphrase=None):
        key_info = UvnIdentityDatabase._lookup_key_info(gpg, owner, target, key_type)
        if key_info is None:
            return None
        key_pub = gpg.export_keys([key_info['fingerprint']])
        if with_secret:
            key_pri = gpg.export_keys([key_info['fingerprint']],
                        secret=True, passphrase=passphrase)
            if not key_pri:
                return None
            logger.debug("loaded private key: {}", key_info['fingerprint'])
        else:
            key_pri = ""
        return GpgKey(fingerprint=key_info["fingerprint"],
                    public=key_pub, private=key_pri)
    
    def _gen_key(self, passphrase, admin, admin_name, target, key_type,
            sign_key=None, sign_passphrase=None):
        key_info = GpgKeyInfo(key_type, admin, target)
        key_desc = str(key_info)
        gpg_input = self.gpg.gen_key_input(
                            key_type=self.key_algo,
                            key_length=self.key_algo,
                            name_real=admin_name,
                            name_comment=key_desc,
                            name_email=admin,
                            passphrase=passphrase)
        key_gpg = self.gpg.gen_key(gpg_input)
        # Sign key if requested
        if sign_key is not None:
            logger.debug("automated key signing not implemented: key={}, sign_key={}",
                key_gpg, sign_key)
            # UvnIdentityDatabase.sign_key("generated key", str(key_gpg),
            #     gpg=self.gpg, sign_key=sign_key, passphrase=sign_passphrase)
        self.dirty = True
        key_pub = self.gpg.export_keys([str(key_gpg)])
        key_pri = self.gpg.export_keys([str(key_gpg)],
                        secret=True, passphrase=passphrase)
        key_info = UvnIdentityDatabase._lookup_key_info(self.gpg, admin, target, key_type)
        key = GpgKey(fingerprint=key_info["fingerprint"], public=key_pub, private=key_pri)
        logger.debug("generated key: owner={}, target={}, type={}, fingerp={}",
                admin, target, key_type, key.fingerprint)
        return key

    def _initialize_registry_id(self, **kwargs):
        admin = kwargs.get("admin")
        admin_name = kwargs.get("admin_name")
        address = kwargs.get("address")
        basedir = kwargs.get("basedir")

        registry_id = kwargs.get("registry_id")
        if registry_id is not None:
            admin = registry_id.admin
            admin_name = registry_id.admin_name
            address = registry_id.address
            basedir = registry_id.basedir

        try:
            if self.packaged:
                # Load cell private key to "log in"
                logger.debug("logging in to UVN cell: {} ({})",
                    self.pkg_cell, self.cell_admin)
                cell_secret = self._secret_cell(self.pkg_cell, self.cell_admin)
                cell_key = UvnIdentityDatabase._load_key(
                                self.gpg, self.cell_admin, self.pkg_cell,
                                GpgKeyInfo.TYPE_CELL,
                                with_secret=True, passphrase=cell_secret)
                if cell_key is None:
                    raise IdentityError(
                        "failed to login to UVN cell {}".format(self.pkg_cell))

            with_secret = not self.packaged
            passphrase = self._secret(admin, required=with_secret)

            # Always try to lookup master key, possibly to "log in" (if not packaged)
            if not with_secret:
                logger.debug("loading UVN key: {} ({})", registry_id.address, registry_id.admin)
            elif registry_id is not None:
                logger.debug("logging in to UVN: {} ({})", registry_id.address, registry_id.admin)
            else:
                logger.debug("initializing UVN database: {} ({})", address, admin)
            
            registry_key = UvnIdentityDatabase._load_key(
                                self.gpg, admin, address, GpgKeyInfo.TYPE_ROOT,
                                with_secret=with_secret, passphrase=passphrase)
            
            if with_secret and registry_key is None and registry_id is not None:
                raise IdentityError(
                        "failed to login to UVN {}".format(registry_id.address))

            if registry_id is None:
                if registry_key is None:
                    logger.debug("generating key for UVN: {} ({})",
                        address, admin)
                    passphrase = self._secret_random(admin)
                    key_info = GpgKeyInfo.uvn_key(admin, address)
                    registry_key = self._gen_key(
                                    passphrase,
                                    admin,
                                    admin_name,
                                    address,
                                    GpgKeyInfo.TYPE_ROOT)
                else:
                    logger.debug("found key for UVN: {} ({})", address, admin)

                registry_id = UvnRegistryIdentity(
                                admin=admin,
                                admin_name=admin_name,
                                address=address,
                                basedir=basedir,
                                key=registry_key)
            else:
                registry_id.key = registry_key

            logger.debug("initialized db for {}: {}", registry_id.address, self.data_dir)
            return registry_id

        except Exception as e:
            logger.error("failed to initialize db: {}", {
                "admin": admin,
                "admin_name": admin_name,
                "address": address,
                "basedir": basedir,
                "data_dir": self.data_dir
            })
            raise e

    def register_cell(self, **kwargs):
        admin = kwargs["admin"]
        admin_name = kwargs["admin_name"]
        address = kwargs["address"]
        name = kwargs["name"]
        generate = kwargs.get("generate", False)
        with_secret = kwargs.get("with_secret", generate)
        try:
            # Try to search for a key for the cell's administrator
            passphrase = None
            if with_secret:
                passphrase = self._secret_cell(name, admin)
            cell_key = UvnIdentityDatabase._load_key(self.gpg,
                        admin, name, GpgKeyInfo.TYPE_CELL,
                        with_secret=with_secret, passphrase=passphrase)

            # If not found, generate a new key
            if cell_key is None:
                if not generate:
                    raise IdentityError("no key found for {} in {}".format(
                            admin, self.data_dir))
                logger.debug("generating key for cell: {} ({})", name, admin)
                passphrase = self._secret_random(admin)
                master_secret = self._secret(required=True)
                cell_key = self._gen_key(
                                passphrase,
                                admin,
                                admin_name,
                                name,
                                GpgKeyInfo.TYPE_CELL,
                                sign_key=self.registry_id.key.fingerprint,
                                sign_passphrase=master_secret)
            else:
                logger.debug("found key for cell: {} ({})", name, admin)

            cell_rec = UvnCellRecord(
                            name=name,
                            admin=admin,
                            address=address,
                            key=cell_key)

            self.cells[name] = cell_rec
            
            logger.debug("initialized cell: {} ({})",
                name, admin)

            return cell_rec

        except Exception as e:
            logger.error("failed to add cell: {}", {
                "admin": admin,
                "admin_name": admin_name,
                "address": address,
                "data_dir": self.data_dir
            })
            raise e
    
    @staticmethod
    def _encrypt_file(gpg,
            file_path,
            key,
            what="data",
            passphrase=None,
            sign_key=None,
            sign_only=False,
            out_file=None,
            sig_file=None):
        if gpg is None:
            raise ValueError("invalid gpg engine")
        file_path = pathlib.Path(file_path)
        if not file_path.exists():
            raise ValueError("file not found: {}".format(file_path))
        outdir = file_path.parent
        sig_file = None
        if sign_key:
            if sig_file is None:
                sig_file = pathlib.Path(str(outdir / file_path.name) +
                                UvnDefaults["identity_db"]["ext_signature"])
            logger.debug("signing file: input={}, key={}, sig={}",
                file_path, sign_key, sig_file)
            with file_path.open("rb") as input:
                sign_result = gpg.sign_file(input,
                                keyid=sign_key,
                                passphrase=passphrase,
                                detach=True,
                                output=str(sig_file))
                if not sign_result:
                    raise CryptoError("failed to sign {} with key: {}".format(what, sign_key))
        if not sign_only:
            if out_file is None:
                out_file = pathlib.Path(str(outdir / file_path.name) +
                            UvnDefaults["identity_db"]["ext_encrypted"])
            logger.debug("encrypting file: input={}, key={}, out={}",
                file_path, key, out_file)
            with file_path.open("rb") as input:
                encrypt_result = gpg.encrypt_file(input, key,
                                    passphrase=passphrase,
                                    output=str(out_file),
                                    armor=False)
                if not encrypt_result.ok:
                    raise CryptoError(
                        "failed to encrypt {}: {}".format(
                            what, encrypt_result.status))
        return {
            "file_path": file_path,
            "encoded": not sign_only,
            "output": out_file,
            "signature": sig_file
        }

    @staticmethod
    def _decrypt_file(
            gpg,
            file_path,
            key,
            sig_file=None,
            enc_file=None,
            what="data",
            passphrase=None,
            verify_only=False):
        if gpg is None:
            raise ValueError("invalid gpg engine")
        file_path = pathlib.Path(file_path)
        outdir = file_path.parent

        if not verify_only:
            if enc_file is None:
                enc_file = pathlib.Path(str(outdir / file_path.stem) +
                                UvnDefaults["identity_db"]["ext_encrypted"])
            logger.debug("decrypting file: input={}, key={}, out={}",
                enc_file, key, file_path)
            with enc_file.open("rb") as f:
                decrypt_result = gpg.decrypt_file(f, key,
                                    passphrase=passphrase,
                                    output=str(file_path))
                if not decrypt_result.ok:
                    raise CryptoError(
                        "failed to decrypt {}: {}".format(
                            what, decrypt_result.status))
                # logger.debug("writing decrypted file: {}", file_path)
                # with file_path.open("wb") as output:
                #     output.write(decrypt_result)
        
        if sig_file is None:
            sig_file = pathlib.Path(str(outdir / file_path.stem) +
                            UvnDefaults["identity_db"]["ext_signature"])
        logger.debug("verifying file: input={}, sig={}", file_path, sig_file)
        with sig_file.open("rb") as sig:
            try:    
                verified = gpg.verify_file(sig, str(file_path))
            except Exception as e:
                raise CryptoError("failed to verify signature for file {}".format(file_path))
            if (verified.trust_level is not None and
                    verified.trust_level < verified.TRUST_FULLY):
                raise CryptoError("insufficient trust level for file {}: found={} expected={}".format(
                        file_path, verified.trust_level, verified.TRUST_FULLY))
        
        return {
            "file_path": file_path,
            "decoded": not verify_only,
            "enc_file": enc_file,
            "sig_file": sig_file
        }

    @staticmethod
    def _encrypt_data(gpg, data, key, what="data", passphrase=None, sign_key=None, sign_only=False):
        if gpg is None:
            raise ValueError("invalid gpg engine")
        if sign_key:
            sign_result = gpg.sign(data,
                            keyid=sign_key,
                            passphrase=passphrase,
                            detach=True)
            if not sign_result:
                raise CryptoError("failed to sign {} with key: {}".format(what, sign_key))
            signature = str(sign_result)
            data = "\n".join([data, signature])
        if not sign_only:
            encrypt_result = gpg.encrypt(data, key, passphrase=passphrase)
            if not encrypt_result.ok:
                raise CryptoError(
                    "failed to encrypt {}: {}".format(what, encrypt_result.status))
            data = str(encrypt_result)
        return data

    @staticmethod
    def _decrypt_data(gpg, data, key=None, what="data", passphrase=None, verify_only=False):
        if gpg is None:
            raise ValueError("invalid gpg engine")
        if not verify_only:
            decrypt_result = gpg.decrypt(data, key, passphrase=passphrase)
            if not decrypt_result.ok:
                raise CryptoError(
                    "failed to decrypt {}: {}".format(
                        what, decrypt_result.status))
            dec_data = str(decrypt_result)
        else:
            dec_data = data

        try:
            data_end = dec_data.index("\n-----BEGIN PGP SIGNATURE-----\n\n")
            has_signature = True
        except ValueError as e:
            data_end = len(dec_data)
            has_signature = False
        data = dec_data[0:data_end]

        if has_signature:
            signature = dec_data[dec_data.index("-----BEGIN PGP SIGNATURE-----\n\n"):]
            # Write signature to a temporary file
            tmp_file_fd, tmp_file_path = tempfile.mkstemp(prefix="uno_sig", suffix="_verify")
            tmp_file_path = pathlib.Path(str(tmp_file_path))
            try:
                with tmp_file_path.open("w") as tmp_sign_file:
                    tmp_sign_file.write(signature)
                    tmp_sign_file.flush()
                verified = gpg.verify_data(str(tmp_file_path), data.encode())
                if not verified:
                    raise CryptoError("failed to verify signature for {}".format(what))
                if (verified.trust_level is None or
                    verified.trust_level < verified.TRUST_FULLY):
                    # raise CryptoError("insufficient trust level for {}".format(what))
                    logger.warning("insufficient trust level for {}", what)
            finally:
                os.close(tmp_file_fd)
                tmp_file_path.unlink()
        elif verify_only:
            raise CryptoError("no signature found to verify")

        return data

    def _export_manifest(
            self,
            basedir,
            deployed_cell=None,
            target_cell=None,
            persist_file=UvnDefaults["identity_db"]["persist_file"]):
        outfile = basedir / persist_file
        logger.debug("exporting identity DB to {}", outfile)
        args = self.get_export_args()
        yml(self, to_file=outfile,
            public_only=True,
            deployed_cell=deployed_cell,
            target_cell=target_cell,
            **args)

    def _export_secrets(self, basedir):
        basedir = pathlib.Path(basedir)
        self._export_registry_secret(basedir)
        for c in self.cells.values():
            self._export_cell_secret(basedir, c)
        # if len(self._auto_secrets) > 0:
        #     logger.activity("automatically generated secrets (not shown again):")
        #     for s in self._auto_secrets.items():
        #         logger.activity("{}: {}", *s)

    def _export_registry_secret(
            self,
            basedir,
            secret_file=UvnDefaults["identity_db"]["secret_file"],
            key_file=UvnDefaults["identity_db"]["key_file"]):
        secret = self._secret()
        if secret is not None:
            secret_file = basedir / secret_file
            with secret_file.open("w") as outfile:
                outfile.write(secret)
            key_file = basedir / key_file
            with key_file.open("w") as outfile:
                outfile.write(self.registry_id.key.private)
        else:
            logger.debug("no secret to export for registry to {}", basedir)

    def _export_cell_secret(
            self,
            basedir,
            cell_record,
            cell_secret_file_fmt=UvnDefaults["identity_db"]["cell_secret_file_fmt"],
            cell_key_file_fmt=UvnDefaults["identity_db"]["cell_key_file_fmt"],
            required=False):
        secret = self._secret_cell(cell_record.name, cell_record.admin)
        if secret is not None:
            secret_file = basedir / cell_secret_file_fmt.format(cell_record.name)
            with secret_file.open("w") as outfile:
                outfile.write(secret)
            # key_file = basedir / cell_key_file_fmt.format(c.name)
            # with key_file.open("w") as outfile:
            #     outfile.write(c.key.private)
        elif required:
            logger.error("no secret to export for cell {} to {}",
                cell_record.name, basedir)
        else:
            logger.debug("no secret to export for cell {} to {}",
                cell_record.name, basedir)

    def export(self):
        self._export_manifest(self.registry_id.basedir)
        self._export_secrets(self.registry_id.basedir)

    def export_cell(self,
            registry,
            pkg_dir,
            deployment=None,
            tgt_cell_cfg=None,
            tgt_cell=None):

        db_dir = pkg_dir / self.data_dir_rel

        logger.debug("exporting identity database to {}", db_dir)

        if tgt_cell is None:
            tgt_cell = tgt_cell_cfg.cell

        # lookup cell record
        tgt_cell_record = self.get_cell_record(tgt_cell.id.name)
        if tgt_cell_record is None:
            raise ValueError("unregistered cell: {}".format(
                    tgt_cell.id.name))
        
        # Try to load cell's private key, ignore errors if not available
        if not tgt_cell_record.key.private:
            try:
                secret = self._secret_cell(
                            tgt_cell_record.name, tgt_cell_record.admin)
                key = UvnIdentityDatabase._load_key(self.gpg,
                        tgt_cell_record.admin, tgt_cell_record.name,
                        GpgKeyInfo.TYPE_CELL,
                        with_secret=True, passphrase=secret)
                tgt_cell_record.key = key
            except Exception as e:
                logger.exception(e)
                logger.warning("failed to load private key for {}",
                    tgt_cell_record.name)

        if not tgt_cell_record.key.private:
            logger.warning("no private key exported to {}'s database",
                    tgt_cell.id.name)

        db_dir.mkdir(parents=True, exist_ok=True)

        cell_gpg = gnupg.GPG(gnupghome=str(db_dir))
        cell_gpg.encoding = self.key_encoding

        # Import cell public keys (target's private key if available)
        # imported_keys = []

        def _import_key(cell, private_key, public_key):
            if private_key:
                logger.debug("importing private key for {} ({}) to {}",
                    cell.id.name, cell.id.admin, db_dir)
                UvnIdentityDatabase._import_key(
                    cell_gpg,
                    cell.id.admin,
                    cell.id.name,
                    GpgKeyInfo.TYPE_CELL,
                    private_key,
                    trustlevel="TRUST_ULTIMATE")
            logger.debug("importing key for {} ({}) to {}",
                cell.id.name, cell.id.admin, db_dir)
            UvnIdentityDatabase._import_key(
                cell_gpg,
                cell.id.admin,
                cell.id.name,
                GpgKeyInfo.TYPE_CELL,
                public_key,
                trustlevel="TRUST_ULTIMATE")

        if deployment is not None:
            for cell_cfg in deployment.deployed_cells:
                if cell_cfg == tgt_cell_cfg:
                    private_key = tgt_cell_record.key.private
                    cell_record = tgt_cell_record
                else:
                    private_key = None
                    cell_record = self.get_cell_record(cell_cfg.cell.id.name)
                    if cell_record is None:
                        raise ValueError("unregistered cell: {}".format(
                                cell_cfg.cell.id.name))
                _import_key(cell_cfg.cell, private_key, cell_record.key.public)
        else:
            for cell in registry.cells.values():
                if cell == tgt_cell:
                    private_key = tgt_cell_record.key.private
                    cell_record = tgt_cell_record
                else:
                    private_key = None
                    cell_record = self.get_cell_record(cell.id.name)
                    if cell_record is None:
                        raise ValueError("unregistered cell: {}".format(cell.id.name))
                _import_key(cell, private_key, cell_record.key.public)
        
        # Import UVN public key
        logger.debug("importing root key for {} ({}) to {}",
            self.registry_id.address, self.registry_id.admin, db_dir)
        UvnIdentityDatabase._import_key(
            cell_gpg,
            self.registry_id.admin,
            self.registry_id.address,
            GpgKeyInfo.TYPE_ROOT,
            self.registry_id.key.public,
            trustlevel="TRUST_ULTIMATE")
        
        # Export database manifest
        db_manifest = self._export_manifest(pkg_dir,
                            deployed_cell=tgt_cell_cfg,
                            target_cell=tgt_cell)

        # Export cell's secret
        cell_secret = self._export_cell_secret(pkg_dir, tgt_cell_record)

        return (db_dir, db_manifest, cell_secret)

    @staticmethod
    def _import_key(gpg, owner, target, key_type, key_data,
            with_secret=False, passphrase=None, trustlevel=None):
        key_info = GpgKeyInfo(key_type, owner, target)
        import_result = gpg.import_keys(key_data)
        if import_result.count == 0:
            raise IdentityError("failed to import key: {}".format(key_info))
        elif import_result.count != 1:
            raise IdentityError(
                "unexpected number of keys imported for {}: expected=1 imported={}".format(
                key_info, import_result.count))
        fingerp = import_result.fingerprints[0]
        # Lookup key info and check that key_info matches
        try:
            key_record = UvnIdentityDatabase._lookup_key_info(gpg, owner, target, key_type)
            if key_record is None:
                raise CryptoError("imported key not found: {}".format(key_info))
            key_info_db = GpgKeyInfo.parse(key_record["uids"][0])
            if key_info != key_info_db:
                raise ValueError("unexpected imported key info: found={}, expected={}".format(
                    key_info, key_info_db))
        except Exception as e:
            # TODO remove imported key
            # logger.exception(e)
            logger.warning("failed to lookup imported key ({}), possible database inconsistency".format(fingerp))
            raise e
        if trustlevel is not None:
            logger.debug("setting key trust level: key_info={}, fingerp={}, level={}",
                key_info, fingerp, trustlevel)
            trust_result = gpg.trust_keys(fingerp, trustlevel)
            if not trust_result:
                raise CryptoError("failed to set trust level for key {}: {}".format(fingerp, trustlevel))
        logger.debug("imported key: key_info={}, fingerp={}", key_info, fingerp)
        return fingerp

    @staticmethod
    def load(basedir,
             data_dir_rel=UvnDefaults["identity_db"]["path"],
             key_encoding=UvnDefaults["identity_db"]["key_encoding"],
             persist_file=UvnDefaults["identity_db"]["persist_file"]):
        args = UvnIdentityDatabase.get_load_args(
                    basedir=basedir,
                    data_dir_rel=data_dir_rel,
                    key_encoding=key_encoding)
        db_file = args["basedir"] / persist_file
        identity_db = yml_obj(UvnIdentityDatabase,
                        db_file, from_file=True, **args)
        return identity_db
    
    @staticmethod
    def get_load_args(
            identity_db=None,
            basedir=None,
            data_dir_rel=UvnDefaults["identity_db"]["path"],
            key_encoding=UvnDefaults["identity_db"]["key_encoding"]):
        if identity_db is None:
            basedir = pathlib.Path(basedir).resolve()
            passphrase = UvnIdentityDatabase.load_secret()
            db_dir = basedir / data_dir_rel
            gpg = gnupg.GPG(gnupghome=str(db_dir))
            gpg.encoding = key_encoding
        else:
            basedir = identity_db.registry_id.basedir
            passphrase = identity_db._secret(required=True)
            gpg = identity_db.gpg
        return {
            "basedir": basedir,
            "passphrase": passphrase,
            "gpg": gpg
        }
    
    def get_export_args(self):
        return {
            "passphrase": self._secret(required=True),
            "gpg": self.gpg,
            "key": self.registry_id.key.fingerprint
        }

    @staticmethod
    def encrypt_file(what, file_path, **kwargs):
        key = kwargs.get("key")
        sign_key = kwargs.get("sign_key", key)
        passphrase = kwargs.get("passphrase")
        gpg = kwargs.get("gpg")
        if key is None:
            return data
        return UvnIdentityDatabase._encrypt_file(
                    gpg, file_path, key,
                    what=what,
                    passphrase=passphrase,
                    sign_key=sign_key)
    
    @staticmethod
    def decrypt_file(what, file_path, **kwargs):
        key = kwargs.get("key")
        gpg = kwargs.get("gpg")
        passphrase = kwargs.get("passphrase")
        if gpg is None:
            return data
        return UvnIdentityDatabase._decrypt_file(
                    gpg, file_path, key,
                    what=what,
                    passphrase=passphrase)

    @staticmethod
    def sign_data(what, data, **kwargs):
        key = kwargs.get("key")
        sign_key = kwargs.get("sign_key", key)
        passphrase = kwargs.get("passphrase")
        gpg = kwargs.get("gpg")
        if key is None:
            return data
        return UvnIdentityDatabase._encrypt_data(
                    gpg, data, key,
                    what=what,
                    passphrase=passphrase,
                    sign_key=sign_key,
                    sign_only=True)
    
    @staticmethod
    def verify_data(what, data, **kwargs):
        gpg = kwargs.get("gpg")
        passphrase = kwargs.get("passphrase")
        if gpg is None:
            return data
        return UvnIdentityDatabase._decrypt_data(gpg, data,
                    what=what,
                    passphrase=passphrase,
                    verify_only=True)
    
    @staticmethod
    def sign_key(what, key, **kwargs):
        gpg = kwargs["gpg"]
        sign_key = kwargs["sign_key"]
        passphrase = kwargs["passphrase"]
        try:
            key_info_db = gpg.list_keys(keys=key)
            if len(key_info_db) != 1:
                raise CryptoError("key not found in database: {}".format(key))
            sig_pre = key_info_db[0]["sigs"]

            # Unfortunately this command still asks for a password
            # so it can't be used in a fully automated way
            exec_command([
                    "echo",
                    "".join(["'", passphrase, "'"]),
                    "|",
                    gpg.gpgbinary,
                    "--passphrase-fd", "0",
                    "--homedir", gpg.gnupghome,
                    "-u", sign_key,
                    "--quick-sign-key", key
                ],
                shell=True,
                fail_msg="failed to sign key {} with {}".format(key, sign_key),
                exception=CryptoError)
            
            # Check that the signature was added
            key_info_db = gpg.list_keys(keys=key)
            if len(key_info_db) != 1:
                raise CryptoError("key not found in database: {}".format(key))
            sig_post = key_info_db[0]["sigs"]
            
            if len(sig_post) <= len(sig_pre):
                raise CryptoError("new signature not found in key record: {}".format(key_info_db[0]))

            exec_command([
                    "echo",
                    "".join(["'", passphrase, "'"]),
                    "|",
                    gpg.gpgbinary,
                    "--homedir", gpg.gnupghome,
                    "--passphrase-fd", "0",
                    "--check-sigs", key
                ],
                shell=True,
                fail_msg="failed to sign key {} with {}".format(key, sign_key),
                exception=CryptoError)
            
        except Exception as e:
            logger.exception(e)
            raise e
    
    @staticmethod
    def _bootstrap_cell_keys(
            tmp_gpg,
            cell_admin,
            cell_name,
            uvn_admin,
            uvn_address,
            uvn_public_key,
            cell_public_key,
            cell_private_key,
            cell_secret):
        # Import cell keys into bootstrap db
        with cell_private_key.open("rb") as input:
            input_data = input.read()
            key_fingerp_priv = UvnIdentityDatabase._import_key(
                tmp_gpg, cell_admin, cell_name,
                GpgKeyInfo.TYPE_CELL, input_data,
                trustlevel="TRUST_ULTIMATE")
        
        with cell_public_key.open("rb") as input:
            input_data = input.read()
            key_fingerp_pub = UvnIdentityDatabase._import_key(
                tmp_gpg, cell_admin, cell_name,
                GpgKeyInfo.TYPE_CELL, input_data,
                trustlevel="TRUST_ULTIMATE")
        
        # Import UVN public key into bootstrap db
        with uvn_public_key.open("rb") as input:
            input_data = input.read()
            root_key_fingerp = UvnIdentityDatabase._import_key(
                tmp_gpg, uvn_admin, uvn_address,
                GpgKeyInfo.TYPE_ROOT, input_data,
                trustlevel="TRUST_ULTIMATE")
        
        # Load cell secret passphrase
        with cell_secret.open("r") as input:
            secret = input.read()
            if not secret:
                raise UvnException(f"no secret specified for cell: {cell_name}")

        return key_fingerp_priv, key_fingerp_pub, root_key_fingerp, secret

    @staticmethod
    def bootstrap_cell(
            bootstrap_dir,
            uvn_address,
            uvn_admin,
            cell_name,
            cell_admin,
            cell_pkg,
            cell_sig,
            registry=None,
            uvn_public_key=None,
            cell_public_key=None,
            cell_private_key=None,
            cell_secret=None,
            keep=False):
        bootstrap_install = registry is None

        # Create a temporary directory to store the bootstrap gpg database
        tmp_db_dir = tempfile.mkdtemp(
                        prefix="{}-{}-".format(uvn_address, cell_name),
                        suffix="-bootstrap")

        cell_pkg_out = pathlib.Path(tmp_db_dir) / cell_pkg.stem

        logger.debug("decrypting package to {}", cell_pkg_out)

        try:
            if bootstrap_install:
                tmp_gpg = gnupg.GPG(gnupghome=str(tmp_db_dir))
                tmp_gpg.encoding = UvnDefaults["identity_db"]["key_encoding"]

                (key_fingerp_priv,
                 key_fingerp_pub,
                 root_key_fingerp,
                 secret) = UvnIdentityDatabase._bootstrap_cell_keys(tmp_gpg,
                    cell_admin=cell_admin,
                    cell_name=cell_name,
                    uvn_admin=uvn_admin,
                    uvn_address=uvn_address,
                    uvn_public_key=uvn_public_key,
                    cell_public_key=cell_public_key,
                    cell_private_key=cell_private_key,
                    cell_secret=cell_secret)
                
                gpg = tmp_gpg
            else:
                # Load cell and uvn keys from identity db
                cell_record = registry.identity_db.get_cell_record(cell_name)
                secret = UvnIdentityDatabase.load_secret_cell(cell_name)
                key_fingerp_priv = cell_record.key.fingerprint
                key_fingerp_pub = cell_record.key.fingerprint
                root_key_fingerp = registry.key.fingerprint

                gpg = registry.identity_db.gpg

            # Decrypt package archive
            decrypt_result = UvnIdentityDatabase._decrypt_file(
                                gpg,
                                cell_pkg_out,
                                key_fingerp_priv,
                                sig_file=cell_sig,
                                enc_file=cell_pkg,
                                what="cell package",
                                passphrase=secret,
                                verify_only=False)
            logger.debug("verified and decrypted package {}", cell_pkg_out.stem)

            # if bootstrap_install:
            #     extract_dir = bootstrap_dir
            # else:
            #     extract_dir = tmp_db_dir

            logger.debug("extracting archive {} to {}", cell_pkg_out.stem, bootstrap_dir)
            shutil.unpack_archive(str(cell_pkg_out), extract_dir=bootstrap_dir,
                format=UvnDefaults["cell"]["pkg"]["clear_format"])

            # if not bootstrap_install:
            #     # Copy package contents onto installation directory
            #     # TODO use python instead of cp
            #     # In Python 3.8+ shutil.copytree() takes a `dirs_exist_ok`
            #     # parameter which allows it to overwrite existing directories
            #     archive_tmp_dir = tmp_db_dir
            #     exec_command(
            #         ["cp", "-rvp",
            #             "{}/*".format(extract_dir),
            #             "{}/*".format(install_prefix)],
            #         fail_msg="failed to update cell")

        finally:
            # Delete temporary directory
            if not keep:
                shutil.rmtree(str(tmp_db_dir))
            else:
                logger.warning("[tmp] not deleted: {}", tmp_db_dir)

    class _YamlSerializer(YamlSerializer):
        def repr_yml(self, py_repr, **kwargs):
            yml_repr = dict()
            yml_repr["key_length"] = py_repr.key_length
            yml_repr["key_algo"] = py_repr.key_algo
            yml_repr["key_encoding"] = py_repr.key_encoding
            yml_repr["key_server"] = py_repr.key_server
            yml_repr["data_dir_rel"] = str(py_repr.data_dir_rel)
            yml_repr["registry_id"] = repr_yml(py_repr.registry_id, **kwargs)
            # Serialize additional fields for cell-specific exports
            target_cell = kwargs.get("target_cell", kwargs.get("deployed_cell"))
            if target_cell is not None:
                yml_repr["cell_db"] = True
                yml_repr["pkg_cell"] = target_cell.id.name
                yml_repr["cell_admin"] = target_cell.id.admin
                yml_repr["cell_address"] = target_cell.id.address
                cell_record = py_repr.get_cell_record(target_cell.id.name)
                yml_repr["cell_key"] = cell_record.key.fingerprint
            return yml_repr
    
        def repr_py(self, yml_repr, **kwargs):
            py_repr = UvnIdentityDatabase(
                            registry_id=repr_py(UvnRegistryIdentity,
                                            yml_repr["registry_id"], **kwargs),
                            cell_db=yml_repr.get("cell_db", False),
                            pkg_cell=yml_repr.get("pkg_cell", None),
                            cell_key=yml_repr.get("cell_key", None),
                            cell_admin=yml_repr.get("cell_admin", None),
                            cell_address=yml_repr.get("cell_address", None),
                            data_dir_rel=yml_repr["data_dir_rel"],
                            key_length=yml_repr["key_length"],
                            key_algo=yml_repr["key_algo"],
                            key_encoding=yml_repr["key_encoding"],
                            key_server=yml_repr["key_server"])
            return py_repr
        
        def _file_format_out(self, yml_str, **kwargs):
            return UvnIdentityDatabase.sign_data(
                    "database manifest", yml_str, **kwargs)

        def _file_format_in(self, yml_str, **kwargs):
            return UvnIdentityDatabase.verify_data(
                    "database manifest", yml_str, **kwargs)


