# Cloud Plugins

`uno` supports integration with some cloud backends to make it easier to share packages with users securely and
to sends notifications via e-mail.

## Google Plugin

Google is supported as a backend for uploading generated files to Google Drive, and send notifications via GMail.


1. Follow the "Prerequisites" sections of the [OAuth 2.0 for Web Server Applications guide](https://developers.google.com/identity/protocols/oauth2/web-server).

   Configured the following access scopes:

   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/drive.appdata`
   - `https://www.googleapis.com/auth/drive.file`
   - `https://www.googleapis.com/auth/gmail.send`

   Download the credentials file and save it locally as `credentials.json`.

2. In order to upload files, create a folder on your Google Drive and copy the folder id from the URL (the last part after `folders/`).
   Then, upload packages from the UVN registry with `uno export-cloud`:

   ```sh
   cd my-uvn/

   uno export-cloud \
     --cloud-provider google \
     --cloud-provider-args '{credentials_file: /path/to/credentials.json}' \
     --cloud-storage-args '{upload_folder: "<FOLDER_ID>"}'
   ```

   After running the command, credentials and configuration will be cached, so you can skip some arguments in following invocation
   in the same directory:

   ```sh
   uno export-cloud --cloud-provider google -r my-uvn/
   ```

3. Download and extract a cell package using `uno install-cloud`:

   ```sh
   uno install-cloud \
     -r my-cell \
     -u my-uvn \
     -c my-cell \
     --cloud-provider google \
     --cloud-provider-args '{credentials_file: /path/to/credentials.json}' \
     --cloud-storage-args '{upload_folder: "<FOLDER_ID>"}'
   ```

4. Send an email to a user with `uno notify`:

   ```sh
   cd my-uvn/

   # Send message to a user
   uno notify user johndoe@example.org \
     --cloud-provider google \
     -S "Hello UVN!" \
     -B "This message sent to you from uno."

   # Send message to a cell's owner
   uno notify cell my-cell \
     --cloud-provider google \
     -S "Hello UVN!" \
     -B "This message sent to you from uno."

   # Send message to particle's owner
   uno notify particle my-particle \
     --cloud-provider google \
     -S "Hello UVN!" \
     -B "This message sent to you from uno."

   # Send message to the uvn's owner
   uno notify uvn \
     --cloud-provider google \
     -S "Hello UVN!" \
     -B "This message sent to you from uno."
   ```
