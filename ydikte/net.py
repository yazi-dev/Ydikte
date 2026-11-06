"""Cancellation token and a small HTTP client whose requests can be aborted mid-flight."""

import http.client
import json
import socket
import ssl
import threading
import urllib.parse
import uuid


class Cancelled(Exception):
    pass


class NetworkError(Exception):
    """The server could not be reached: offline, DNS, timeout."""


class ApiError(Exception):
    """The server answered with an error status."""

    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class CancelToken:
    """Set by Esc. Runs registered closers so a blocked socket or process dies now."""

    def __init__(self):
        self._lock = threading.Lock()
        self._closers = []
        self._cancelled = False

    @property
    def cancelled(self):
        return self._cancelled

    def check(self):
        if self._cancelled:
            raise Cancelled()

    def add_closer(self, fn):
        with self._lock:
            if not self._cancelled:
                self._closers.append(fn)
                return
        fn()

    def remove_closer(self, fn):
        with self._lock:
            if fn in self._closers:
                self._closers.remove(fn)

    def cancel(self):
        with self._lock:
            self._cancelled = True
            closers, self._closers = self._closers, []
        for fn in closers:
            try:
                fn()
            except Exception:
                pass


def request(url, headers, body, timeout, cancel):
    """POST. Returns (status, response bytes)."""
    cancel.check()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(
            parts.hostname, parts.port, timeout=timeout, context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)

    def abort():
        sock = conn.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    try:
        conn.connect()
        cancel.add_closer(abort)
        cancel.check()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    except (OSError, http.client.HTTPException) as exc:
        cancel.check()
        raise NetworkError(str(exc)) from None
    finally:
        cancel.remove_closer(abort)
        conn.close()


def _error_message(data):
    try:
        err = json.loads(data).get("error")
        if isinstance(err, dict):
            return str(err.get("message", err))[:300]
        if err:
            return str(err)[:300]
    except (ValueError, AttributeError):
        pass
    return data[:200].decode("utf-8", "replace")


def post_json(url, api_key, payload, timeout, cancel):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    status, data = request(url, headers, json.dumps(payload).encode("utf-8"), timeout, cancel)
    if status != 200:
        raise ApiError(status, _error_message(data))
    try:
        return json.loads(data)
    except ValueError:
        raise ApiError(status, "response was not JSON") from None


def post_multipart(url, api_key, fields, filename, file_bytes, timeout, cancel):
    boundary = uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            .encode("utf-8"))
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode("utf-8"))
    chunks.append(file_bytes)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {api_key}",
    }
    status, data = request(url, headers, b"".join(chunks), timeout, cancel)
    if status != 200:
        raise ApiError(status, _error_message(data))
    try:
        return json.loads(data)
    except ValueError:
        raise ApiError(status, "response was not JSON") from None
