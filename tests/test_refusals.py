"""What the user is told when the server says no.

It used to be "403 Client Error: Forbidden for url: ...", raised before the
reply was read -- and the reply is the only thing that says *who* refused.
Piwigo answering in its own JSON means Piwigo turned the request down; an
HTML page means something in front of Piwigo stopped it first, and nothing the
program can do differently will get through.  The two need entirely different
responses from the person reading the message.

The 403 page below is the one photos.fanac.org actually returned on
2026-10-29, when its server began refusing every file upload.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import AlbumHierarchy as ah                                    # noqa: E402

SERVER_403 = (
    '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" '
    '"http://www.w3.org/TR/html4/strict.dtd">\n<html><head>\n'
    '<title>403 Forbidden</title>\n</head><body>\n<h1>Forbidden</h1>\n'
    "<p>You don't have permission to access this resource.</p>\n"
    "<p>Additionally, a 403 Forbidden error was encountered while trying to "
    "use an ErrorDocument to handle the request.</p>\n</body></html>\n")


class WhoRefused(unittest.TestCase):

    def say(self, status, body, what="the upload"):
        return ah._explain_refusal(status, body, what)

    def test_a_server_filter_is_named_as_the_server_s_doing(self):
        got = self.say(403, SERVER_403)
        self.assertIn("before it reached Piwigo", got)
        self.assertIn("not this program", got)
        self.assertIn("whoever looks after the server", got)

    def test_it_keeps_the_http_code_for_whoever_has_to_fix_it(self):
        self.assertIn("HTTP 403", self.say(403, SERVER_403))

    def test_piwigo_s_own_refusal_is_quoted_not_blamed_on_the_server(self):
        """A 403 that Piwigo sent itself -- a bad security token, say -- is a
        different thing entirely, and must not be dressed up as a filter."""
        got = self.say(403, '{"stat":"fail","err":403,"message":"Invalid security token"}')
        self.assertIn("Piwigo refused", got)
        self.assertIn("Invalid security token", got)
        self.assertNotIn("before it reached Piwigo", got)

    def test_not_logged_in_says_where_the_account_comes_from(self):
        got = self.say(401, '{"stat":"fail","err":401,"message":"Access denied"}')
        self.assertIn("Access denied", got)
        self.assertIn("Piwigo Credentials.json", got)

    def test_too_large_is_called_too_large(self):
        self.assertIn("too large", self.say(413, "<html>Request Entity Too Large</html>"))

    def test_a_server_failure_is_offered_as_possibly_temporary(self):
        self.assertIn("temporary", self.say(502, "<html>Bad Gateway</html>"))

    def test_anything_else_quotes_the_server_without_its_markup(self):
        got = self.say(404, "<html><body><h1>Not Found</h1><p>No such page</p></body></html>")
        self.assertIn("HTTP 404", got)
        self.assertIn("Not Found No such page", got)
        self.assertNotIn("<", got)

    def test_an_empty_reply_is_not_an_error_in_itself(self):
        got = self.say(418, "")
        self.assertIn("HTTP 418", got)
        self.assertNotIn("It said", got)

    def test_no_message_carries_raw_html(self):
        for status in (400, 403, 404, 413, 500):
            self.assertNotIn("<", self.say(status, SERVER_403), status)


class _Reply:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        import json
        return json.loads(self.text)


class _Session:
    """Stands in for requests.Session and answers every POST the same way."""

    def __init__(self, status, text):
        self.reply = _Reply(status, text)
        self.posted = []
        self.verify = False

    def post(self, url, **kw):
        self.posted.append(kw)
        return self.reply


class TheCallsUseIt(unittest.TestCase):
    """Wiring, not wording: that what the user sees comes from the reply."""

    def client(self, status, text):
        c = ah.PiwigoClient("https://piwigo.invalid", "u", "p",
                            verify_ssl=False, rate_limit_calls_per_second=1000)
        c.session = _Session(status, text)
        return c

    def test_an_upload_refused_by_the_server_says_so(self):
        c = self.client(403, SERVER_403)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xd9")
        try:
            with self.assertRaises(RuntimeError) as caught:
                c.upload_image(f.name, category_id=1, name="es-jk00120.jpg")
        finally:
            Path(f.name).unlink(missing_ok=True)
        self.assertIn("before it reached Piwigo", str(caught.exception))

    def test_any_other_call_refused_by_the_server_says_so_too(self):
        c = self.client(403, SERVER_403)
        with self.assertRaises(RuntimeError) as caught:
            c.get_albums()
        self.assertIn("before it reached Piwigo", str(caught.exception))
        self.assertIn("pwg.categories.getList", str(caught.exception))

    def test_a_refused_login_never_repeats_the_password(self):
        """Error text ends up in dialogs, logs and screenshots."""
        c = self.client(403, SERVER_403)
        with self.assertRaises(RuntimeError) as caught:
            c.login("someone", "not-a-real-password")
        self.assertNotIn("not-a-real-password", str(caught.exception))

    def test_a_refusal_is_not_retried(self):
        """Retrying a rule the server enforces only delays the message."""
        c = self.client(403, SERVER_403)
        with self.assertRaises(RuntimeError):
            c.get_albums()
        self.assertEqual(len(c.session.posted), 1)


if __name__ == "__main__":
    unittest.main()
