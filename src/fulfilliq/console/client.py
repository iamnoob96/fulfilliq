"""HTTP-only console adapter; all domain computations remain in FastAPI."""

import os

import httpx
import pandas as pd


def csv_export(frame: pd.DataFrame) -> bytes:
    """Export displayed rows and escape spreadsheet formula-like text cells."""
    safe = frame.map(lambda value: "'" + value if isinstance(value, str)
                     and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value)
    return safe.to_csv(index=False).encode("utf-8")


class BackendError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BackendClient:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = url or os.environ.get("FULFILIQ_API_URL", "http://127.0.0.1:8000")
        self.token = token if token is not None else os.environ.get("FULFILIQ_WRITE_TOKEN", "")

    def request(self, method: str, path: str, *, params=None, body=None):
        headers = {"Authorization": "Bearer " + self.token} if self.token else {}
        try:
            response = httpx.request(method, self.url + path, params=params, json=body,
                                     headers=headers, timeout=90)
            if response.is_error:
                try:
                    detail = response.json().get("detail", response.text[:300])
                except ValueError:
                    detail = response.text[:300]
                raise BackendError(f"Backend returned {response.status_code}: {detail}",
                                   status_code=response.status_code)
            return response.json()
        except httpx.RequestError as exc:
            raise BackendError("Backend unreachable. Start both services with scripts/start_app.sh.") from exc

    def get(self, path: str, **params):
        return self.request("GET", "/api/v1" + path,
                            params={key: value for key, value in params.items() if value is not None})

    def post(self, path: str, body: dict):
        return self.request("POST", "/api/v1" + path, body=body)

    def put(self, path: str, body: dict):
        return self.request("PUT", "/api/v1" + path, body=body)
