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
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource


import io
from functools import cached_property
from pathlib import Path

from uno.registry.cloud import CloudProvider

from uno.core.exec import exec_command
from uno.registry.cloud.cloud_storage import CloudStorage
from uno.registry.database import Database
from uno.registry.versioned import Versioned

from .google_drive_cloud_storage import GoogleDriveCloudStorage
from .gmail_cloud_email_server import GmailCloudEmailServer

class GoogleCloudProvider(CloudProvider):
  AUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.appdata",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.send",
  ]

  PROPERTIES = [
    "credentials_file",
  ]

  INITIAL_CREDENTIALS_FILE = lambda self: self.root / "credentials.json"

  STORAGE = GoogleDriveCloudStorage
  EMAIL_SERVER = GmailCloudEmailServer

  def __init__(self, **properties) -> None:
    super().__init__(**properties)
    self.__cached_services = {}


  @classmethod
  def svc_class(cls) -> str:
    return "google"


  def prepare_credentials_file(self, val: str | Path) -> None:
    internal_credentials = self.INITIAL_CREDENTIALS_FILE()
    if val != internal_credentials:
      internal_credentials.parent.mkdir(exist_ok=True, parents=True)
      exec_command(["cp", "-av", val, internal_credentials])
      self.log.warning("cached Google OAuth credentials: {}", internal_credentials)
      self.updated_property("credentials_file")
    # return Path(val)
    return None


  def serialize_credentials_file(self, val: Path) -> str:
    return str(val)


  def _validate(self) -> None:
    if not self.credentials_file.exists():
      raise RuntimeError("Google OAuth credentials file missing", self.credentials_file)


  @property
  def token_file(self) -> Path:
    return self.root / "token.json"


  def create_api_service(self, api: str, version: str="v3", refresh: bool=False) -> None:
    if not refresh:
      cached = self.__cached_services.get(api)
      if cached is not None:
        return cached

    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if self.token_file.exists():
      self.log.activity("loading cached credentials: {}", self.token_file)
      creds = Credentials.from_authorized_user_file(self.token_file, self.AUTH_SCOPES)
      self.log.info("loaded cached credentials: {}", self.token_file)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
      if creds and creds.expired and creds.refresh_token:
        self.log.activity("credentials expired")
        creds.refresh(Request())
        self.log.info("credentials refreshed")
      else:
        self.log.warning("new credentials required")
        flow = InstalledAppFlow.from_client_secrets_file(
            self.credentials_file, self.AUTH_SCOPES
        )
        creds = flow.run_local_server(port=0)
        self.log.warning("new credentials generated")
      # Save the credentials for the next run
      with self.token_file.open("w") as token:
        token.write(creds.to_json())
      self.log.activity("credentials stored to disk: {}", self.token_file)
    
    self.log.info("connecting to Google {} API...", api.capitalize())
    self.__cached_services[api] = build(api, version, credentials=creds)
    self.log.warning("connected to Google {} API", api.capitalize())
    return self.__cached_services[api]

