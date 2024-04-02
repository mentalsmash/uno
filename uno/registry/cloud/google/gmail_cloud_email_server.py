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
from googleapiclient.discovery import Resource

from functools import cached_property

from uno.registry.cloud import CloudEmailServer, CloudEmailServerError

import base64
from email.mime.text import MIMEText


class GmailCloudEmailServer(CloudEmailServer):
  @cached_property
  def __service(self) -> Resource:
    return self.provider.create_api_service("gmail", version="v1")


  def send(self, to: str, subject: str, body: str) -> None:
    try:
      message = MIMEText(body)
      message['to'] = to
      message['subject'] = subject
      create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
      self.log.info("sending e-mail to <{}>: {}", to, subject)
      message = (self.__service.users().messages().send(userId="me", body=create_message).execute())
      self.log.warning("e-mail sent to <{}>: {}", to, subject)
    except Exception as e:
      self.log.error("failed to send e-mail to {}: {}", to, subject)
      self.log.exception(e)
      raise CloudEmailServerError("failed to send e-mail", to, subject)

