###############################################################################
# Copyright 2020-2024 Andrea Sorbini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###############################################################################
from googleapiclient.discovery import Resource

from functools import cached_property

from uno.registry.cloud import CloudEmailServer, CloudEmailServerError

import base64

# from email.mime.text import MIMEText
from email.message import EmailMessage


class GmailCloudEmailServer(CloudEmailServer):
  EQ_PROPERTIES = [
    "parent",
  ]

  @cached_property
  def __service(self) -> Resource:
    return self.provider.create_api_service("gmail", version="v1")

  def send(self, sender: str, to: str, subject: str, body: str) -> None:
    try:
      # message = MIMEText(body)
      message = EmailMessage()
      message["To"] = to
      # TODO(asorbini) The "From" is not actually read by GMail, so the message will
      # show up as coming from the cloud provider's user's email.
      message["From"] = sender
      message["Subject"] = subject
      message.set_content(body)

      create_message = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
      self.log.info("sending e-mail from <{}> to <{}>: {}", sender, to, subject)
      message = self.__service.users().messages().send(userId="me", body=create_message).execute()
      self.log.warning("e-mail sent from <{}> to <{}>: {}", sender, to, subject)
    except Exception as e:
      self.log.error("failed to send e-mail from <{}> to <{}>: {}", sender, to, subject)
      self.log.exception(e)
      raise CloudEmailServerError("failed to send e-mail", sender, to, subject)
