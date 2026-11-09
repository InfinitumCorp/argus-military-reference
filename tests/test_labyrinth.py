import io
import json
import unittest
import urllib.error
from argus.labyrinth import LabyrinthClient, _NoRedirect


class LabyrinthTests(unittest.TestCase):
    def test_requires_cid_token_and_https(self):
        with self.assertRaises(ValueError):
            LabyrinthClient("http://public.example/api/labyrinth", lambda: "session")
        with self.assertRaises(ValueError):
            LabyrinthClient("https://user:secret@cid.example/api/labyrinth", lambda: "session")
        client = LabyrinthClient("https://cid.example/api/labyrinth", lambda: "")
        with self.assertRaises(ValueError):
            client.repositories()

    def test_explicit_transport_uses_fixed_namespace_and_no_org_claims(self):
        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return io.BytesIO(b'{"content":"selected artifact"}')
        opener = Opener()
        client = LabyrinthClient("https://cid.example/api/labyrinth", lambda: "lbrnth_session", opener=opener)
        self.assertEqual(client.load("repo", "commit", "selected.json"), "selected artifact")
        body = json.loads(opener.request.data)
        self.assertEqual(body["product"], "argus")
        self.assertNotIn("orgId", body)
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer lbrnth_session")
        self.assertEqual(opener.timeout, 10)

    def test_large_payloads_do_not_reach_network(self):
        class Never:
            def open(self, *_args, **_kwargs):
                raise AssertionError("must not send")
        client = LabyrinthClient("https://cid.example/api/labyrinth", lambda: "session", opener=Never())
        with self.assertRaises(ValueError):
            client.save("repo", "large.txt", "x" * (2 * 1024 * 1024), None)

    def test_redirects_never_forward_bearer(self):
        import urllib.request
        request = urllib.request.Request("https://cid.example/api/labyrinth")
        with self.assertRaises(urllib.error.HTTPError):
            _NoRedirect().redirect_request(request, None, 307, "redirect", {}, "https://evil.example")
