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
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.discovery import Resource

import io
from functools import cached_property
from pathlib import Path
from uno.registry.cloud import CloudStorage, CloudStorageFile, CloudStorageError


class GoogleDriveCloudStorage(CloudStorage):
  EQ_PROPERTIES = [
    "parent",
  ]
  PROPERTIES = [
    "upload_folder",
  ]

  def INITIAL_UPLOAD_FOLDER(self) -> str | None:
    if self.folder_id_file.exists():
      return self.folder_id_file.read_text()
    return None

  def prepare_upload_folder(self, val: str) -> None:
    if not val:
      raise RuntimeError("invalid upload folder id")
    result = None
    if val != self.upload_folder:
      self.folder_id_file.parent.mkdir(exist_ok=True, parents=True)
      self.folder_id_file.write_text(val)
      result = val
      self.log.warning("upload folder: {}", self.upload_folder)
      self.updated_property("upload_folder")
    return result

  def _validate(self) -> None:
    if self.upload_folder is None:
      raise RuntimeError("no upload folder specified")

  @property
  def folder_id_file(self) -> Path:
    return self.root / "folder.id"

  @cached_property
  def __remote_files(self) -> dict[str, str]:
    return self.__list_remote_files(self.upload_folder)

  @cached_property
  def __service(self) -> Resource:
    return self.provider.create_api_service("drive")

  def upload(self, files: list[CloudStorageFile]) -> list[CloudStorageFile]:
    self.log.info("uploading {} files to Google Drive", len(files))
    for i, file in enumerate(files):
      try:
        self.log.activity("uploading [{}/{}] {}", i + 1, len(files), file.local_path)
        media = MediaFileUpload(file.local_path, mimetype=file.type.mimetype())
        # If a file with the same name already exists in the remote folder
        # reuse its fileId and update its contents, otherwise create a new one
        existing_id = self.__remote_files.get(file.name)
        if existing_id is None:
          file_metadata = {
            "name": file.name,
            "parents": [self.upload_folder],
          }
          # pylint: disable=maybe-no-member
          uploaded_file = (
            self.__service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
          )
          file.remote_url = uploaded_file.get("id")
        else:
          # file_metadata["fileId"] = existing_id
          uploaded_file = (
            self.__service.files().update(media_body=media, fileId=existing_id).execute()
          )
          file.remote_url = existing_id
        self.log.info(
          "uploaded [{}/{}] {} -> {}", i + 1, len(files), file.local_path, file.remote_url
        )
      except Exception as e:
        self.log.error("upload failed: {}", file.local_path)
        self.log.exception(e)
        raise CloudStorageError("upload failed", file)
    return files

  def __list_remote_files(self, folder_id: str) -> dict[str, str]:
    remote_files = {}
    page_token = None
    try:
      while True:
        # pylint: disable=maybe-no-member
        response = (
          self.__service.files()
          .list(
            # q=f"mimeType='{mimetype}'",
            q=f"'{folder_id}' in parents",
            spaces="drive",
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
          )
          .execute()
        )
        for file in response.get("files", []):
          remote_files[file.get("name")] = file.get("id")
          self.log.debug("folder file [{}] {} {}", folder_id, file.get("id"), file.get("name"))

        page_token = response.get("nextPageToken", None)
        if page_token is None:
          break
    except Exception as e:
      self.log.error("failed to list folder files: {}", folder_id)
      self.log.exception(e)
      raise CloudStorageError("failed to list folder files", folder_id)

    return remote_files

  def download(self, files: list[CloudStorageFile]) -> list[CloudStorageFile]:
    # Make sure we query the remote files if we need them
    self.__dict__.pop("__remote_files", None)
    self.log.info("downloading {} files from Google Drive", len(files))
    for i, file in enumerate(files):
      try:
        if file.remote_url is None:
          file.remote_url = self.__remote_files[file.name]
        # pylint: disable=maybe-no-member
        request = self.__service.files().get_media(fileId=file.remote_url)
        file_data = io.FileIO(file.local_path, mode="w")
        downloader = MediaIoBaseDownload(file_data, request)
        done = False
        self.log.activity(
          "starting download [{}/{}] {} -> {}", i + 1, len(files), file.remote_url, file.local_path
        )
        while done is False:
          status, done = downloader.next_chunk()
          self.log.activity(
            "download [{}/{}] progress: {}% {}",
            i + 1,
            len(files),
            int(status.progress() * 100),
            file.local_path,
          )
        self.log.info("downloaded [{}/{}] {}", i + 1, len(files), file.local_path)
      except Exception as e:
        self.log.error("download failed: {}", file.local_path)
        self.log.exception(e)
        raise CloudStorage("download failed", file)
    return files
