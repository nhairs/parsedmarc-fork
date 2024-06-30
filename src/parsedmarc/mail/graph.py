# Future
from __future__ import annotations

# Standard Library
from enum import Enum
from functools import lru_cache
from pathlib import Path
import sys
from time import sleep
from typing import Any

if sys.version_info < (3, 10):
    # Installed
    from typing_extensions import TypeAlias
else:
    from typing import TypeAlias

# Installed
from azure.identity import (
    AuthenticationRecord,
    ClientSecretCredential,
    DeviceCodeCredential,
    TokenCachePersistenceOptions,
    UsernamePasswordCredential,
)
from msgraph.core import GraphClient

# Package
from parsedmarc.log import logger
from parsedmarc.mail.mailbox_connection import MailboxConnection


class AuthMethod(Enum):
    # pylint: disable=invalid-name
    DeviceCode = 1
    UsernamePassword = 2
    ClientSecret = 3


Credential: TypeAlias = "DeviceCodeCredential | UsernamePasswordCredential | ClientSecretCredential"


def _get_cache_args(token_path: Path, allow_unencrypted_storage: bool):
    cache_args: dict[str, Any] = {
        "cache_persistence_options": TokenCachePersistenceOptions(
            name="parsedmarc",
            allow_unencrypted_storage=allow_unencrypted_storage,
        )
    }
    auth_record = _load_token(token_path)
    if auth_record:
        cache_args["authentication_record"] = AuthenticationRecord.deserialize(auth_record)
    return cache_args


def _load_token(token_path: Path) -> str | None:
    if not token_path.exists():
        return None
    with token_path.open() as token_file:
        return token_file.read()


def _cache_auth_record(record: AuthenticationRecord, token_path: Path):
    token = record.serialize()
    with token_path.open("w") as token_file:
        token_file.write(token)


def _generate_credential(auth_method: str, token_path: Path, **kwargs) -> Credential:
    credential: Credential
    if auth_method == AuthMethod.DeviceCode.name:
        credential = DeviceCodeCredential(
            client_id=kwargs["client_id"],
            client_secret=kwargs["client_secret"],
            disable_automatic_authentication=True,
            tenant_id=kwargs["tenant_id"],
            **_get_cache_args(
                token_path,
                allow_unencrypted_storage=kwargs["allow_unencrypted_storage"],
            ),
        )
        return credential

    if auth_method == AuthMethod.UsernamePassword.name:
        credential = UsernamePasswordCredential(
            client_id=kwargs["client_id"],
            client_credential=kwargs["client_secret"],
            disable_automatic_authentication=True,
            username=kwargs["username"],
            password=kwargs["password"],
            **_get_cache_args(
                token_path,
                allow_unencrypted_storage=kwargs["allow_unencrypted_storage"],
            ),
        )
        return credential

    if auth_method == AuthMethod.ClientSecret.name:
        credential = ClientSecretCredential(
            client_id=kwargs["client_id"],
            tenant_id=kwargs["tenant_id"],
            client_secret=kwargs["client_secret"],
        )
        return credential
    raise RuntimeError(f"Auth method {auth_method} not found")


class MSGraphConnection(MailboxConnection):
    """MailboxConnection to a Microsoft account via the Micorsoft Graph API"""

    def __init__(
        self,
        auth_method: str,
        client_id: str,
        client_secret: str,
        token_file: str,
        allow_unencrypted_storage: bool,
        username: str | None = None,
        password: str | None = None,
        tenant_id: str | None = None,
        mailbox: str | None = None,
    ):
        """
        Args:
            auth_method:
            mailbox:
            client_id:
            client_secret:
            username:
            password:
            tenant_id:
            token_file:
            allow_unencrypted_storage:
        """
        token_path = Path(token_file)
        credential = _generate_credential(
            auth_method,
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            tenant_id=tenant_id,
            token_path=token_path,
            allow_unencrypted_storage=allow_unencrypted_storage,
        )
        client_params: dict[str, Any] = {"credential": credential}
        if isinstance(credential, (DeviceCodeCredential, UsernamePasswordCredential)):
            scopes = ["Mail.ReadWrite"]
            # Detect if mailbox is shared
            if mailbox and username != mailbox:
                scopes = ["Mail.ReadWrite.Shared"]
            auth_record = credential.authenticate(scopes=scopes)
            _cache_auth_record(auth_record, token_path)
            client_params["scopes"] = scopes

        self._client = GraphClient(**client_params)
        self.mailbox_name = mailbox or username

    def create_folder(self, folder_name: str) -> None:
        sub_url = ""
        path_parts = folder_name.split("/")
        if len(path_parts) > 1:  # Folder is a subFolder
            parent_folder_id = None
            for folder in path_parts[:-1]:
                parent_folder_id = self._find_folder_id_with_parent(folder, parent_folder_id)
            sub_url = f"/{parent_folder_id}/childFolders"
            folder_name = path_parts[-1]

        request_body = {"displayName": folder_name}
        request_url = f"/users/{self.mailbox_name}/mailFolders{sub_url}"
        resp = self._client.post(request_url, json=request_body)
        if resp.status_code == 409:
            logger.debug(f"Folder {folder_name} already exists, skipping creation")
        elif resp.status_code == 201:
            logger.debug(f"Created folder {folder_name}")
        else:
            logger.warning(f"Unknown response {resp.status_code} {resp.json()}")

    def fetch_messages(self, reports_folder: str, **kwargs) -> list[str]:
        """Returns a list of message UIDs in the specified folder"""
        folder_id = self._find_folder_id_from_folder_path(reports_folder)
        url = f"/users/{self.mailbox_name}/mailFolders/" f"{folder_id}/messages"
        batch_size = kwargs.get("batch_size")
        if not batch_size:
            batch_size = 0
        emails = self._get_all_messages(url, batch_size)
        return [email["id"] for email in emails]

    def _get_all_messages(self, url: str, batch_size: int):
        messages: list
        params: dict[str, Any] = {"$select": "id"}
        if batch_size and batch_size > 0:
            params["$top"] = batch_size
        else:
            params["$top"] = 100
        result = self._client.get(url, params=params)
        if result.status_code != 200:
            raise RuntimeError(f"Failed to fetch messages {result.text}")
        data = result.json()
        messages = data["value"]
        # Loop if next page is present and not obtained message limit.
        while "@odata.nextLink" in result.json() and (
            batch_size == 0 or batch_size - len(messages) > 0
        ):
            result = self._client.get(data["@odata.nextLink"])
            if result.status_code != 200:
                raise RuntimeError(f"Failed to fetch messages {result.text}")
            messages.extend(data["value"])
        return messages

    def mark_message_read(self, message_id: str):
        """Marks a message as read"""
        url = f"/users/{self.mailbox_name}/messages/{message_id}"
        resp = self._client.patch(url, json={"isRead": "true"})
        if resp.status_code != 200:
            raise RuntimeWarning(f"Failed to mark message read {resp.status_code}: {resp.json()}")

    def fetch_message(self, message_id: str) -> str:
        url = f"/users/{self.mailbox_name}/messages/{message_id}/$value"
        result = self._client.get(url)
        if result.status_code != 200:
            raise RuntimeWarning(f"Failed to fetch message {result.status_code}: {result.json()}")
        self.mark_message_read(message_id)
        return result.text

    def delete_message(self, message_id: str):
        url = f"/users/{self.mailbox_name}/messages/{message_id}"
        resp = self._client.delete(url)
        if resp.status_code != 204:
            raise RuntimeWarning(f"Failed to delete message {resp.status_code}: {resp.json()}")

    def move_message(self, message_id: str, folder_name: str):
        folder_id = self._find_folder_id_from_folder_path(folder_name)
        request_body = {"destinationId": folder_id}
        url = f"/users/{self.mailbox_name}/messages/{message_id}/move"
        resp = self._client.post(url, json=request_body)
        if resp.status_code != 201:
            raise RuntimeWarning(f"Failed to move message {resp.status_code}: {resp.json()}")

    def keepalive(self):
        # Not needed
        pass

    def watch(self, check_callback, check_timeout):
        """Checks the mailbox for new messages every n seconds"""
        while True:
            sleep(check_timeout)
            check_callback(self)

    @lru_cache(maxsize=10)
    def _find_folder_id_from_folder_path(self, folder_name: str) -> str:
        path_parts = folder_name.split("/")
        parent_folder_id = None
        if len(path_parts) > 1:
            for folder in path_parts[:-1]:
                folder_id = self._find_folder_id_with_parent(folder, parent_folder_id)
                parent_folder_id = folder_id
            return self._find_folder_id_with_parent(path_parts[-1], parent_folder_id)
        return self._find_folder_id_with_parent(folder_name, None)

    def _find_folder_id_with_parent(self, folder_name: str, parent_folder_id: str | None):
        sub_url = f"/{parent_folder_id}/childFolders" if parent_folder_id is not None else ""
        url = f"/users/{self.mailbox_name}/mailFolders{sub_url}?$filter=displayName eq '{folder_name}'"
        folders_resp = self._client.get(url)
        if folders_resp.status_code != 200:
            raise RuntimeWarning(f"Failed to list folders. {folders_resp.json()}")
        folders: list = folders_resp.json()["value"]
        matched_folders = [folder for folder in folders if folder["displayName"] == folder_name]
        if len(matched_folders) == 0:
            raise RuntimeError(f"folder {folder_name} not found")
        selected_folder = matched_folders[0]
        return selected_folder["id"]
