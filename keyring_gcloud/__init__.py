"""
A keyring backend for Google Cloud Platform.

It uses another keyring as an actual storage backend. This backend is only a proxy
that encodes/decodes the credentials and refreshes it if we believe it's expired.

Google access tokens are opaque, so we can't inspect them to evaluate actual
expiration. So we basically use 1 hour "because people on the internet said so".
"""

import base64
from datetime import datetime, timedelta, timezone
from typing import Self
from keyring.backend import KeyringBackend, get_all_keyring
from keyring.backends.chainer import ChainerBackend
from google.auth.transport.requests import Request
from google.auth.credentials import Credentials
import google.auth
from dataclasses import dataclass
from os import environ

try:
    from keyring.compat import properties
except ImportError:
    # Workaround for Poetry up to at least 1.8.3
    from keyring._compat import properties

get_all_keyring()

# Refresh token if it's older than this
default_expiry = timedelta(minutes=55)  # 1 hour minus a little bit


@dataclass
class GoogleCredential:
    token: str | None = None
    expiry: datetime | None = None

    @property
    def valid(self) -> bool:
        return (
            self.token is not None
            and self.expiry is not None
            and self.expiry >= datetime.now(timezone.utc)
        )

    @classmethod
    def from_encoded(cls, encoded_credentials: str | None) -> Self:
        """
        Decodes the encoded credentials and returns a new instance.

        Encoded format is "<expiry>:<token>" where both are base64 encoded.
        <expiry> is a datetime in ISO format and <token> is the access token as a
        string.
        """
        try:
            assert encoded_credentials, "whoops. fallback to except handler..."
            encoded_expiry, encoded_token = encoded_credentials.split(":")
            expiry_str = base64.b64decode(encoded_expiry).decode("ascii")
            expiry = datetime.fromisoformat(expiry_str)
            token = base64.b64decode(encoded_token).decode("ascii")
            return cls(token, expiry)
        except Exception:
            return cls()

    def refresh(self) -> None:
        credentials: Credentials
        credentials, _ = google.auth.default()  # type: ignore

        # If credentials are expired, refresh them
        if credentials.expired:
            credentials.refresh(Request())

        # Get the access token
        self.token = credentials.token  # type: ignore
        self.expiry = datetime.now(timezone.utc) + default_expiry

    def encode(self) -> str | None:
        """
        Encodes the credentials and returns it as a string.

        Encoded format is "<expiry>:<token>" where both are base64 encoded.
        <expiry> is a datetime in ISO format and <token> is the access token as a
        string.
        """
        if self.token is None:
            return None

        assert self.expiry

        access_token_bytes = self.token.encode("ascii")
        encoded_token = base64.b64encode(access_token_bytes).decode("ascii")

        expiry_bytes = self.expiry.isoformat().encode("ascii")
        encoded_expiry = base64.b64encode(expiry_bytes).decode("ascii")

        encoded_credentials = f"{encoded_expiry}:{encoded_token}"
        return encoded_credentials


class GoogleCloudKeyring(KeyringBackend):
    backend: KeyringBackend

    def __init__(self):
        super().__init__()
        self._set_backend()

    def _set_backend(self):
        viable_backends = sorted(self.get_viable_backends(), key=lambda b: -b.priority)
        viable_backends = [
            b for b in viable_backends if b not in (GoogleCloudKeyring, ChainerBackend)
        ]
        if len(viable_backends) < 1:
            raise Exception("No viable backends")

        self.backend = viable_backends[0]()

    @properties.classproperty
    def priority(self) -> float:
        return 1

    def get_password(self, service: str, username: str) -> str | None:
        secret = self.backend.get_password(service, username)
        if not self._should_intercept(service, username):
            return secret

        cred = GoogleCredential.from_encoded(secret)
        if not cred.valid:
            cred.refresh()
            if encoded := cred.encode():
                self.backend.set_password(service, username, encoded)
        return cred.token

    def set_password(self, service: str, username: str, password: str) -> None:
        if self._should_intercept(service, username):
            expiry = datetime.now(timezone.utc) + default_expiry
            cred = GoogleCredential(password, expiry=expiry)
            if encoded := cred.encode():
                password = encoded
        self.backend.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        self.backend.delete_password(service, username)

    def _should_intercept(self, service: str, username: str) -> bool:
        always_intercept = len(environ.get("KEYRING_GCLOUD_ON", "")) > 0
        if always_intercept:
            return True

        # TODO consider making this less dumb
        special_username = environ.get("KEYRING_GCLOUD_USERNAME", "oauth2accesstoken")
        return username == special_username
