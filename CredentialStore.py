"""CredentialStore — shared credential and parameter management for Piwigo apps.

Each Piwigo application stores its configuration in two files in its own directory:

  Piwigo Credentials.json   — url, username, password, verify_ssl
                              (identical filename for every app)
  <AppName> Params.json     — operational settings: rate limits, pixel caps, etc.
                              (app-specific filename supplied at construction)

On the first run after migration from a combined params file, if the credentials
file does not yet exist but the params file contains credential keys, those keys
are automatically written to the credentials file and stripped from the params
file.  On every subsequent run any credential keys that linger in the params file
are also removed.

Typical usage::

    from CredentialStore import CredentialStore, CredentialError

    _store = CredentialStore(app_dir, "MyApp Params.json")

    # In a worker thread:
    try:
        creds  = _store.load_credentials()   # raises CredentialError on failure
        params = _store.load_op_params()      # returns {} if file missing / unreadable
    except CredentialError as exc:
        # show exc to user
"""
from __future__ import annotations

import json
from pathlib import Path

CREDS_FILENAME = "Piwigo Credentials.json"
CREDS_KEYS     = ("url", "username", "password", "verify_ssl")


class CredentialError(Exception):
    """Raised when credentials cannot be loaded; message is user-facing."""


class CredentialStore:
    """Credential and operational-parameter manager for one Piwigo application."""

    def __init__(self, app_dir: "Path | str", params_filename: str) -> None:
        self._creds_file  = Path(app_dir) / CREDS_FILENAME
        self._params_file = Path(app_dir) / params_filename

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def params_file(self) -> Path:
        """Where the operational settings are kept.  For showing a user which
        file a program is actually reading."""
        return self._params_file

    @property
    def credentials_file(self) -> Path:
        """Where the credentials are kept.  The path only -- a program may say
        where they live, but must not put their contents on screen."""
        return self._creds_file

    def load_credentials(self) -> dict:
        """Return the credential dict.

        Primary source: Piwigo Credentials.json.
        Fallback: the app params file (migrates on first use).
        Either way, credential keys still in the params file are removed.
        Raises CredentialError with a user-facing message on any failure.
        """
        if self._creds_file.exists():
            data = self._read_json(self._creds_file)
            self._validate(data, self._creds_file)
            self._strip_creds_from_params()
            return data

        if not self._params_file.exists():
            raise CredentialError(
                f"No credentials file was found.\n\n"
                f"Please create:\n  {self._creds_file}\n\n"
                "with:\n"
                "{\n"
                '  "url":      "https://your-piwigo-site.example.com",\n'
                '  "username": "your-username",\n'
                '  "password": "your-password",\n'
                '  "verify_ssl": true\n'
                "}"
            )
        params = self._read_json(self._params_file)
        self._validate(params, self._params_file)
        creds = {k: params[k] for k in CREDS_KEYS if k in params}
        self.save_credentials(creds)
        self._strip_creds_from_params()
        return creds

    def load_op_params(self) -> dict:
        """Return operational (non-credential) settings from the params file.

        Never raises.  Returns {} if the file is missing or unreadable.
        Credential keys are always excluded even if still present in the file.
        """
        if not self._params_file.exists():
            return {}
        try:
            data = json.loads(self._params_file.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if k not in CREDS_KEYS}
        except Exception:
            return {}

    def set_op_param(self, key: str, value) -> bool:
        """Set one operational setting in the params file, keeping the rest.

        Reads the file as it stands rather than writing back a dict from
        load_op_params, so nothing else in it is disturbed.  Returns True if the
        new value reached the disk: a caller that has just promised the user
        their choice will be remembered needs to know when it was not.
        """
        try:
            data = {}
            if self._params_file.exists():
                data = json.loads(self._params_file.read_text(encoding="utf-8"))
            data[key] = value
            self._params_file.write_text(
                json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def save_credentials(self, creds: dict) -> None:
        """Write *creds* to the credentials file (best-effort; silent on failure)."""
        try:
            self._creds_file.write_text(
                json.dumps(creds, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ── private ───────────────────────────────────────────────────────────────

    def _read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CredentialError(f"Could not read {path.name}:\n{exc}")

    def _validate(self, data: dict, source: Path) -> None:
        missing = [k for k in ("url", "username", "password") if not data.get(k)]
        if not missing:
            return
        raise CredentialError(
            f"{source.name} is missing required fields: "
            f"{', '.join(missing)}\n\n"
            f"Expected file ({self._creds_file}):\n"
            "{\n"
            '  "url":      "https://your-piwigo-site.example.com",\n'
            '  "username": "your-username",\n'
            '  "password": "your-password",\n'
            '  "verify_ssl": true\n'
            "}"
        )

    def _strip_creds_from_params(self) -> None:
        if not self._params_file.exists():
            return
        try:
            data = json.loads(self._params_file.read_text(encoding="utf-8"))
            if any(k in data for k in CREDS_KEYS):
                stripped = {k: v for k, v in data.items() if k not in CREDS_KEYS}
                self._params_file.write_text(
                    json.dumps(stripped, indent=2), encoding="utf-8"
                )
        except Exception:
            pass
