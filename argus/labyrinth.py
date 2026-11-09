"""Explicit client artifact transport for Labyrinth, by Infinitum Corporation®.

No exercise/mission records are exported automatically. The central service, not
this reference demo or an email/user-id claim, verifies the Cumulus ID credential,
current client organization, role, consent and LBRNTH entitlement.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Labyrinth redirects refused", headers, fp)


class LabyrinthClient:
    def __init__(self, endpoint: str, token: Callable[[], str], *, opener=None):
        url = urllib.parse.urlsplit(endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Labyrinth requires a credential-free HTTPS endpoint")
        self._endpoint = endpoint
        self._token = token
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    def _call(self, **command):
        token = self._token()
        if not isinstance(token, str) or not 1 <= len(token) <= 512 or any(c.isspace() for c in token):
            raise ValueError("Cumulus ID repository sign-in required")
        payload = json.dumps({**command, "product": "argus"}).encode("utf-8")
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError("Labyrinth request too large")
        request = urllib.request.Request(self._endpoint, data=payload, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Labyrinth": "1",
        })
        with self._opener.open(request, timeout=10) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Labyrinth response too large")
            return json.loads(raw)

    def repositories(self):
        return self._call(action="list")

    def create_repository(self, name: str):
        return self._call(action="create", name=name)

    def save(self, repo: str, path: str, content: str, expected_head: str | None, *, message="Save selected ARGUS artifact", branch="main"):
        return self._call(action="save", repo=repo, path=path, content=content, expectedHead=expected_head, message=message, branch=branch)

    def load(self, repo: str, commit: str, path: str):
        return self._call(action="load", repo=repo, commit=commit, path=path)["content"]

    def history(self, repo: str, branch="main", limit=100):
        return self._call(action="history", repo=repo, branch=branch, limit=limit)
