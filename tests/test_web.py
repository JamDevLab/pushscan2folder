"""Web page: auth, CSRF, headers, target editor and config writing (127.0.0.1 only)."""
import errno
import html
import io
import re
import http.client
import logging
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from pushscan2folder import __main__ as cli
from pushscan2folder import web
from pushscan2folder.discovery import Scanner
from pushscan2folder.config import Config, TargetSpec, dump_config, load_config, write_config
from pushscan2folder.service import Target, Trim
from pushscan2folder.status import LogBuffer, ScanRecord, ServiceStatus
from support import CAN_SYMLINK, assert_mode, needs_symlinks

web.POLL_INTERVAL = 0.02   # fast server shutdown between tests

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"
PASSWORD = "correct horse"


class FakeService:
    def __init__(self):
        self.status = ServiceStatus()
        self.requested = []

    def request_targets(self, targets):
        self.requested.append(targets)


class Client:
    """Tiny HTTP client that keeps the session cookie."""

    def __init__(self, port, cookie_name=web.COOKIE):
        self.port = port
        self.cookie = None
        self.cookie_name = cookie_name
        self.last_set_cookie = None

    def request(self, method, path, form=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = dict(headers or {})
        if self.cookie:
            hdrs["Cookie"] = self.cookie
        body = raw
        if form is not None:
            body = urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read().decode()
            set_cookie = resp.getheader("Set-Cookie")
            if set_cookie and set_cookie.startswith(self.cookie_name + "="):
                self.cookie = set_cookie.split(";")[0]
                self.last_set_cookie = set_cookie
            return resp.status, resp, data
        finally:
            conn.close()

    def login(self, password=PASSWORD):
        return self.request("POST", "/login", {"password": password})

    def csrf(self, path="/targets"):
        data = self.request("GET", path)[2]
        marker = 'name="csrf" value="'
        start = data.index(marker) + len(marker)
        return data[start:data.index('"', start)]


class WebTestBase(unittest.TestCase):
    from_env = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.service = FakeService()
        self.logbuf = LogBuffer()
        self.config_path = self.dir / "cfg" / "config.toml"
        self.ctx = web.WebContext(self.service, self.logbuf, "192.0.2.1", self.dir / "scans",
                                  multipage_mode="document", config_path=self.config_path,
                                  targets_from_env=self.from_env)
        self.server, self.thread = web.start_server(self.ctx, PASSWORD, "127.0.0.1", 0)
        self.addCleanup(web.stop_server, self.server, self.thread)
        self.client = Client(self.server.server_address[1])

    def logged_in(self):
        self.assertEqual(self.client.login()[0], 303)
        return self.client


class AuthTests(WebTestBase):
    def test_redirects_to_login(self):
        for path in ("/", "/log", "/targets", "/nope"):
            status, resp, _ = self.client.request("GET", path)
            self.assertEqual(status, 303, path)
            self.assertEqual(resp.getheader("Location"), "/login")

    def test_style_and_login_are_public(self):
        self.assertEqual(self.client.request("GET", "/style.css")[0], 200)
        self.assertEqual(self.client.request("GET", "/login")[0], 200)
        status, resp, data = self.client.request("GET", "/favicon.svg")
        self.assertEqual((status, resp.getheader("Content-Type")), (200, "image/svg+xml"))
        self.assertTrue(data.startswith("<svg"))

    def test_footer_links_source(self):
        _, _, data = self.client.request("GET", "/login")
        self.assertIn('href="https://github.com/JamDevLab/pushscan2folder"', data)
        self.assertIn("AGPL-3.0", data)

    def test_wrong_password(self):
        status, _, data = self.client.login("nope nope nope")
        self.assertEqual(status, 401)
        self.assertIn("Wrong password", data)
        self.assertEqual(self.client.request("GET", "/")[0], 303)

    def test_login_cookie_flags(self):
        status, resp, _ = self.client.login()
        self.assertEqual(status, 303)
        cookie = resp.getheader("Set-Cookie")
        self.assertTrue(cookie.startswith("p2f_session="))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/", cookie)
        self.assertEqual(self.client.request("GET", "/")[0], 200)

    def test_global_lockout(self):
        clock = [1000.0]
        with mock.patch.object(web, "_now", lambda: clock[0]):
            for _ in range(5):
                self.assertEqual(self.client.login("wrong wrong")[0], 401)
            status, _, data = self.client.login()  # correct, but locked
            self.assertEqual(status, 429)
            self.assertIn("Too many attempts", data)
            clock[0] += 61
            self.assertEqual(self.client.login()[0], 303)
            # success reset the counter: four more failures do not lock
            other = Client(self.server.server_address[1])
            for _ in range(4):
                self.assertEqual(other.login("wrong wrong")[0], 401)
            self.assertEqual(other.login()[0], 303)

    def test_session_idle_timeout(self):
        clock = [1000.0]
        with mock.patch.object(web, "_now", lambda: clock[0]):
            self.logged_in()
            clock[0] += web.SESSION_IDLE_SECONDS + 1
            self.assertEqual(self.client.request("GET", "/")[0], 303)

    def test_logout(self):
        self.logged_in()
        csrf = self.client.csrf("/")
        status, _, _ = self.client.request("POST", "/logout", {"csrf": csrf})
        self.assertEqual(status, 303)
        self.assertEqual(self.client.request("GET", "/")[0], 303)


class SecurityTests(WebTestBase):
    def test_headers_on_every_response(self):
        self.logged_in()
        for path in ("/", "/login", "/style.css", "/log", "/missing"):
            _, resp, _ = self.client.request("GET", path)
            for key, value in web.SECURITY_HEADERS.items():
                self.assertEqual(resp.getheader(key), value, (path, key))
        _, resp, _ = Client(self.server.server_address[1]).request("GET", "/")  # redirect
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")

    def test_only_the_external_script(self):
        self.logged_in()
        self.service.status.set_targets([Target("a", Path("/s/a"))])
        for path in ("/", "/log", "/targets", "/login"):
            page = self.client.request("GET", path)[2].lower()
            self.assertFalse(re.search(r"<script(?![^>]*\ssrc=)", page), path)
            self.assertIsNone(re.search(r"<[^>]+\son[a-z]+\s*=", page), path)
            self.assertIsNone(re.search(r"javascript:", page), path)
        for path in ("/", "/log", "/targets"):
            self.assertIn('<script src="/app.js" defer></script>',
                          self.client.request("GET", path)[2], path)
        self.assertNotIn("<script", self.client.request("GET", "/login")[2].lower())

    def test_app_js_and_csp(self):
        status, resp, data = self.client.request("GET", "/app.js")   # public
        self.assertEqual(status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "text/javascript; charset=utf-8")
        self.assertIn("beforeunload", data)
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe", csp)

    def test_login_footer_centered_and_nav_sticky(self):
        self.assertIn('<body class="login-page">', self.client.request("GET", "/login")[2])
        css = self.client.request("GET", "/style.css")[2]
        self.assertIn("body.login-page footer", css)
        self.assertRegex(css, r"nav \{ position:sticky; top:0; z-index:\d+;")

    def test_csrf_missing_and_wrong(self):
        self.logged_in()
        for form in ({}, {"csrf": "wrong"}):
            self.assertEqual(self.client.request("POST", "/logout", form)[0], 403)
            self.assertEqual(self.client.request("POST", "/targets", form)[0], 403)
        self.assertEqual(self.client.request("GET", "/")[0], 200)  # still logged in

    def test_foreign_origin(self):
        self.logged_in()
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets", {"csrf": csrf, "rows": "0"},
                                           headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.client.request("POST", "/login", {"password": PASSWORD},
                                           headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        host = f"127.0.0.1:{self.server.server_address[1]}"
        status, _, _ = self.client.request("POST", "/logout", {"csrf": csrf},
                                           headers={"Origin": f"http://{host}"})
        self.assertEqual(status, 303)

    def test_body_limit(self):
        status, _, _ = self.client.request("POST", "/login", raw=b"x=" + b"a" * (70 * 1024),
                                           headers={"Content-Type":
                                                    "application/x-www-form-urlencoded"})
        self.assertEqual(status, 413)


class NoAuthTests(unittest.TestCase):
    """PUSHSCAN_WEB_AUTH=0 on a network bind: no login, everything else stays."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.service = FakeService()
        self.service.status.set_targets([Target("a", self.dir / "scans" / "a")])
        self.config_path = self.dir / "cfg" / "config.toml"
        write_config(self.config_path, dump_config(Config(targets=[TargetSpec("a")])))
        self.ctx = web.WebContext(self.service, LogBuffer(), "192.0.2.1", self.dir / "scans",
                                  config_path=self.config_path)
        self.server, self.thread = web.start_server(self.ctx, None, "0.0.0.0", 0)
        self.addCleanup(web.stop_server, self.server, self.thread)
        self.client = Client(self.server.server_address[1])

    def test_pages_without_login(self):
        for path in ("/", "/log", "/targets", "/settings", "/config"):
            status, resp, data = self.client.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn("No password set", data, path)
            self.assertNotIn("Log out", data, path)
            for key, value in web.SECURITY_HEADERS.items():
                self.assertEqual(resp.getheader(key), value, (path, key))

    def test_public_host_names_are_refused(self):
        for host in ("evil.example.com", "attacker.com:8080", "nas.example.org"):
            self.assertEqual(self.client.request("GET", "/", headers={"Host": host})[0], 403, host)
            self.assertEqual(self.client.request("POST", "/targets", {"csrf": self.client.csrf()},
                                                 headers={"Host": host})[0], 403, host)
        for host in ("192.168.1.5:8080", "[::1]:8080", "localhost", "nas", "nas.local:8021",
                     "nas.fritz.box", "NAS.LAN."):
            self.assertEqual(self.client.request("GET", "/", headers={"Host": host})[0], 200, host)

    def test_local_host(self):
        self.assertTrue(web.local_host("10.0.0.1"))
        self.assertFalse(web.local_host(None))
        self.assertFalse(web.local_host("example.com"))
        self.assertFalse(web.local_host("local.example.com"))

    def test_login_and_logout_redirect_to_start(self):
        for method, path, form in (("GET", "/login", None), ("POST", "/login", {"password": "x"}),
                                   ("POST", "/logout", {"csrf": "x"})):
            status, resp, _ = self.client.request(method, path, form)
            self.assertEqual((status, resp.getheader("Location")), (303, "/"), path)

    def test_csrf_is_still_required(self):
        csrf = self.client.csrf()
        self.assertEqual(self.client.csrf(), csrf)
        for path in ("/targets", "/settings", "/config"):
            for form in ({}, {"csrf": "wrong"}):
                self.assertEqual(self.client.request("POST", path, form)[0], 403, path)
        self.assertEqual(self.service.requested, [])
        status, _, _ = self.client.request(
            "POST", "/targets", {"csrf": csrf, "rows": "1", "name_0": "a", "existing_0": "1",
                                 "orig_0": "a", "op": "save"})
        self.assertEqual(status, 303)

    def test_csrf_differs_per_process(self):
        other = web.start_server(self.ctx, None, "0.0.0.0", 0)
        self.addCleanup(web.stop_server, *other)
        self.assertNotEqual(Client(other[0].server_address[1]).csrf(), self.client.csrf())

    def test_origin_check_still_enforced(self):
        csrf = self.client.csrf()
        for headers in ({"Origin": "http://evil.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}):
            status, _, _ = self.client.request("POST", "/targets", {"csrf": csrf, "rows": "0"},
                                               headers=headers)
            self.assertEqual(status, 403, headers)

    def test_folder_restriction_still_enforced(self):
        csrf = self.client.csrf()
        status, _, data = self.client.request(
            "POST", "/targets", {"csrf": csrf, "rows": "1", "name_0": "b", "output_0": "../x",
                                 "op": "save"})
        self.assertEqual(status, 400)
        self.assertIn("..", data)
        self.assertEqual(self.service.requested, [])

    def test_login_page_with_password_has_logout(self):
        server, thread = web.start_server(self.ctx, PASSWORD, "127.0.0.1", 0)
        self.addCleanup(web.stop_server, server, thread)
        self.assertTrue(self.ctx.auth)
        client = Client(server.server_address[1])
        client.login()
        data = client.request("GET", "/")[2]
        self.assertIn("Log out", data)
        self.assertNotIn("No password set", data)


class LoopbackNoLoginTests(unittest.TestCase):
    """No password on a loopback bind: no login, a calm note, all checks stay."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.service = FakeService()
        self.service.status.set_targets([Target("a", self.dir / "scans" / "a")])
        self.config_path = self.dir / "cfg" / "config.toml"
        write_config(self.config_path, dump_config(Config(targets=[TargetSpec("a")])))
        self.ctx = web.WebContext(self.service, LogBuffer(), "192.0.2.1", self.dir / "scans",
                                  config_path=self.config_path)
        with mock.patch.dict(os.environ, {}, clear=True):
            password = cli.web_password_setup(None, "127.0.0.1")
        self.assertIsNone(password)
        self.server, self.thread = web.start_server(self.ctx, password, "127.0.0.1", 0)
        self.addCleanup(web.stop_server, self.server, self.thread)
        self.client = Client(self.server.server_address[1])

    def test_page_without_session(self):
        status, _, data = self.client.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("only reachable from this PC", data)
        self.assertNotIn("No password set", data)
        self.assertNotIn("Log out", data)

    def test_host_header_still_checked(self):
        self.assertEqual(self.client.request("GET", "/", headers={"Host": "evil.example.com"})[0],
                         403)

    def test_only_loopback_host_names(self):
        for host in ("nas", "pc.local", "192.168.1.5:8737", "evil.example.com"):
            status = self.client.request("GET", "/", headers={"Host": host})[0]
            self.assertEqual(status, 403, host)
        for host in ("localhost:8737", "127.0.0.1:8737", "[::1]:8737", "LOCALHOST"):
            status = self.client.request("GET", "/", headers={"Host": host})[0]
            self.assertEqual(status, 200, host)

    def test_post_needs_csrf_token(self):
        self.assertEqual(self.client.request("POST", "/targets", {"rows": "0"})[0], 403)
        self.assertEqual(self.client.request("POST", "/targets",
                                             {"csrf": "wrong", "rows": "0"})[0], 403)
        self.assertEqual(self.service.requested, [])

    def test_loopback_addresses(self):
        for address in ("127.0.0.1", "127.0.0.2", "::1", "localhost", "LOCALHOST"):
            self.assertTrue(web.is_loopback(address), address)
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(cli.web_password_setup(None, address), address)
        for address in ("0.0.0.0", "::", "192.168.1.5", "example.com", "", None):
            self.assertFalse(web.is_loopback(address), address)

    def test_other_bind_without_password_is_an_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            for address in ("0.0.0.0", "192.168.1.5", None):
                with self.assertRaises(ValueError, msg=address):
                    cli.web_password_setup(None, address)

    def test_password_file_on_loopback_needs_login(self):
        pw = self.dir / "pw.txt"
        pw.write_text("a-long-password\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            password = cli.web_password_setup(str(pw), "127.0.0.1")
        self.assertEqual(password, "a-long-password")
        server, thread = web.start_server(self.ctx, password, "127.0.0.1", 0)
        self.addCleanup(web.stop_server, server, thread)
        client = Client(server.server_address[1])
        status, resp, _ = client.request("GET", "/")
        self.assertEqual((status, resp.getheader("Location")), (303, "/login"))

    def test_env_password_on_loopback_is_used(self):
        with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD": "a-long-password"},
                             clear=True):
            self.assertEqual(cli.web_password_setup(None, "127.0.0.1"), "a-long-password")


class StartChecksWebTests(unittest.TestCase):
    def test_start_refuses_network_bind_without_password(self):
        keep = {k: v for k, v in os.environ.items() if not k.startswith("PUSHSCAN_")}
        popen = mock.Mock()
        with mock.patch.dict(os.environ, keep, clear=True), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = cli.start_main(["--printer", "192.0.2.1", "start", "--web", "--web-bind", "0.0.0.0"],
                                  popen=popen)
        self.assertEqual(code, 2)
        self.assertIn("needs a password", err.getvalue())
        popen.assert_not_called()

    def test_bind_defaults_to_this_pc_without_password(self):
        keep = {k: v for k, v in os.environ.items() if not k.startswith("PUSHSCAN_")}
        with mock.patch.dict(os.environ, keep, clear=True):
            args, _ = cli.parse_args(["--printer", "192.0.2.1", "run", "--web"])
            self.assertEqual(args.web_bind, "127.0.0.1")
            with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD": "x" * 12}):
                args, _ = cli.parse_args(["--printer", "192.0.2.1", "run", "--web"])
            self.assertEqual(args.web_bind, "0.0.0.0")
            args, _ = cli.parse_args(["--printer", "192.0.2.1", "run", "--web",
                                      "--web-bind", "0.0.0.0"])
            self.assertEqual(args.web_bind, "0.0.0.0")


class NavTests(WebTestBase):
    def test_config_tab_is_its_own_tab(self):
        self.logged_in()
        for path, tab in (("/settings", "Settings"), ("/config", "config.toml")):
            data = self.client.request("GET", path)[2]
            current = re.findall(r'<a class="tab current" href="[^"]+" aria-current="page">([^<]+)<',
                                 data)
            self.assertEqual(current, [tab], path)
        self.assertIn('<a class="tab" href="/config">config.toml</a>',
                      self.client.request("GET", "/")[2])


class PagesTests(WebTestBase):
    def test_status_escapes_values(self):
        st = self.service.status
        st.set_targets([Target("<b>x</b>", Path("/scans/<i>"), session=1,
                               preset={"resolution": 300})])
        st.record(ScanRecord(1.0, "t<script>", "native", 2, ("/s/a<img>.pdf",), "error",
                             "<script>alert(1)</script>"))
        st.poll_failed("<script>boom</script>")
        st.set_busy("x&y")
        st.set_pending(True)
        self.logged_in()
        data = self.client.request("GET", "/")[2]
        self.assertNotIn("<script>", data)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", data)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", data)
        self.assertIn("a&lt;img&gt;.pdf", data)
        self.assertIn("x&amp;y", data)
        self.assertIn("pending", data)
        # quiet update by app.js, plain reload only without JavaScript
        self.assertIn('<noscript><meta http-equiv="refresh" content="10"></noscript>', data)
        self.assertIn('<main data-refresh="10">', data)
        self.assertIn('<script src="/app.js" defer></script>', data)
        self.assertIn("connect-src 'self'", web.SECURITY_HEADERS["Content-Security-Policy"])
        self.assertIn("main[data-refresh]", web.APP_JS)

    def test_status_long_name_note(self):
        self.service.status.set_targets([Target("n" * 30, Path("/s/n"))])
        self.logged_in()
        self.assertIn("shows only the first 25", self.client.request("GET", "/")[2])

    def test_log_page(self):
        for i in range(600):
            self.logbuf.handle(logging.LogRecord("t", logging.INFO, "", 0,
                                                 f"line {i} <script>", None, None))
        self.logged_in()
        data = self.client.request("GET", "/log")[2]
        self.assertNotIn("<script>", data)
        self.assertIn("line 599 &lt;script&gt;", data)
        self.assertIn("line 100 ", data)
        self.assertNotIn("line 99 ", data)


class TargetEditorTests(WebTestBase):
    def form(self, csrf, *rows, count=None):
        form = {"csrf": csrf, "rows": str(count if count is not None else len(rows))}
        for i, row in enumerate(rows):
            for key, value in row.items():
                form[f"{key}_{i}"] = value
        return form

    def ops_form(self, csrf, op, *rows):
        form = self.form(csrf, *rows)
        form["op"] = op
        return form

    def test_open_after_scan_per_target(self):
        self.logged_in()
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets", self.ops_form(
            csrf, "save", {"name": "PC"}, {"name": "Archive", "open": "no"}))
        self.assertEqual(status, 303)
        cfg = load_config(self.config_path)
        self.assertEqual([t.open_after_scan for t in cfg.targets], [None, False])
        page = self.client.request("GET", "/targets")[2]
        self.assertIn('<option value="no" selected>', page)
        status, _, page = self.client.request("POST", "/targets", self.ops_form(
            csrf, "save", {"name": "PC", "open": "always"}))
        self.assertEqual(status, 400)
        self.assertIn("invalid open after scan", page)

    def test_fresh_page_has_one_blank_row(self):
        self.logged_in()
        data = self.client.request("GET", "/targets")[2]
        self.assertEqual(data.count('name="name_'), 1)
        self.assertIn("<h2>New target</h2>", data)
        self.assertNotIn("Changes are not saved yet", data)
        self.assertNotIn("data-dirty", data)

    def test_enter_key_submits_save(self):
        self.logged_in()
        data = self.client.request("GET", "/targets")[2]
        form = data[data.index("<form id=\"targets-form\""):]
        first = re.search(r"<button[^>]*>", form).group(0)
        self.assertIn('name="op" value="save"', first)
        self.assertIn('tabindex="-1"', first)
        self.assertIn('aria-hidden="true"', first)
        self.assertIn('class="sr-only"', first)

    def test_add_keeps_values_and_writes_nothing(self):
        self.logged_in()
        csrf = self.client.csrf()
        status, _, data = self.client.request("POST", "/targets", self.ops_form(
            csrf, "add", {"name": "scan1", "output": "x/y", "res": "600", "docmp": "1"}))
        self.assertEqual(status, 200)
        self.assertIn('name="name_0" value="scan1"', data)
        self.assertIn('name="output_0" value="x/y"', data)
        self.assertIn('<option value="600" selected>', data)
        self.assertIn('name="name_1" value=""', data)
        self.assertNotIn('name="name_2"', data)
        self.assertIn("Changes are not saved yet.", data)
        self.assertIn('data-dirty="1"', data)
        self.assertFalse(self.config_path.exists())
        self.assertEqual(self.service.requested, [])

    def test_move_up_down_and_remove(self):
        self.logged_in()
        csrf = self.client.csrf()
        rows = ({"name": "a"}, {"name": "b"}, {"name": "c"})
        status, _, data = self.client.request("POST", "/targets", self.ops_form(
            csrf, "up_1", *rows))
        self.assertEqual(status, 200)
        names = re.findall(r'name="name_\d" value="(\w*)"', data)
        self.assertEqual(names, ["b", "a", "c"])
        self.assertIn('data-dirty="1"', data)
        self.assertNotIn('value="up_0"', data)          # first card cannot move up
        self.assertNotIn('value="down_2"', data)        # last cannot move down
        _, _, data = self.client.request("POST", "/targets", self.ops_form(
            csrf, "down_0", *rows))
        self.assertEqual(re.findall(r'name="name_\d" value="(\w*)"', data), ["b", "a", "c"])
        _, _, data = self.client.request("POST", "/targets", self.ops_form(
            csrf, "remove_1", *rows))
        self.assertEqual(re.findall(r'name="name_\d" value="(\w*)"', data), ["a", "c"])
        self.assertFalse(self.config_path.exists())
        self.assertEqual(self.service.requested, [])

    def test_saved_order_is_card_order(self):
        self.logged_in()
        csrf = self.client.csrf()
        _, _, data = self.client.request("POST", "/targets", self.ops_form(
            csrf, "down_0", {"name": "a"}, {"name": "b"}, {"name": "c"}))
        # post what the re-rendered form holds
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf, {"name": "b"}, {"name": "a"}, {"name": "c"}))
        self.assertEqual(status, 303)
        self.assertEqual([t.name for t in load_config(self.config_path).targets],
                         ["b", "a", "c"])
        self.assertEqual([t.name for t in self.service.requested[0]], ["b", "a", "c"])

    def test_remove_existing_row_is_refused(self):
        self.logged_in()
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets", self.ops_form(
            csrf, "remove_0", {"name": "a", "existing": "1", "orig": "a"}, {"name": "b"}))
        self.assertEqual(status, 400)

    def test_bad_ops_are_400(self):
        self.logged_in()
        csrf = self.client.csrf()
        rows = ({"name": "a"}, {"name": "b"})
        for op in ("bogus", "up_0", "down_1", "up_2", "down_9", "remove_5", "up_", "up_-1",
                   "up_01x", "ADD", "save ", "", "add_1"):
            status, _, _ = self.client.request("POST", "/targets",
                                               self.ops_form(csrf, op, *rows))
            self.assertEqual(status, 400, op)
        self.assertFalse(self.config_path.exists())

    def test_add_respects_max_rows(self):
        self.logged_in()
        csrf = self.client.csrf()
        form = self.form(csrf, count=web.MAX_ROWS)
        form["op"] = "add"
        status, _, data = self.client.request("POST", "/targets", form)
        self.assertEqual(status, 400)
        self.assertIn("At most", data)

    def test_saving_keeps_a_target_file_name(self):
        self.logged_in()
        self.config_path.parent.mkdir()
        self.config_path.write_text('[[target]]\nname = "a"\nfilename = "bill_{date}"\n')
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets",
                                           self.form(csrf, {"name": "a"}, {"name": "b"}))
        self.assertEqual(status, 303)
        cfg = load_config(self.config_path)
        self.assertEqual([(t.name, t.filename) for t in cfg.targets],
                         [("a", "bill_{date}"), ("b", None)])

    def test_explicit_save_op_saves(self):
        self.logged_in()
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets",
                                           self.ops_form(csrf, "save", {"name": "a"}))
        self.assertEqual(status, 303)

    def test_disabled_when_from_env(self):
        self.ctx.targets_from_env = True
        self.logged_in()
        data = self.client.request("GET", "/targets")[2]
        self.assertIn("PUSHSCAN_TARGETS", data)
        self.assertNotIn('<form method="post" action="/targets"', data)
        csrf = self.client.csrf()
        status, _, _ = self.client.request(
            "POST", "/targets", self.form(csrf, {"name": "a", "docmp": "1"}))
        self.assertEqual(status, 403)
        self.assertFalse(self.config_path.exists())

    def test_disabled_without_config_path(self):
        self.ctx.config_path = None
        self.logged_in()
        self.assertIn("PUSHSCAN_CONFIG", self.client.request("GET", "/targets")[2])

    def test_first_save_creates_file(self):
        self.logged_in()
        csrf = self.client.csrf()
        self.assertIn("does not exist yet", self.client.request("GET", "/targets")[2])
        status, resp, _ = self.client.request("POST", "/targets", self.form(
            csrf,
            {"name": "scan1"},
            {"name": "paperless", "output": "consume/in", "docmp": "1", "res": "600",
             "fmt": "jpeg", "size": "a4", "automp": "1"},
            {"name": ""}))
        self.assertEqual(status, 303)
        self.assertEqual(resp.getheader("Location"), "/")
        cfg = load_config(self.config_path)
        self.assertEqual([t.name for t in cfg.targets], ["scan1", "paperless"])
        self.assertEqual(cfg.targets[0].document_multipage, False)
        assert_mode(self, self.config_path, 0o600)
        p = cfg.targets[1]
        self.assertEqual((p.output, p.document_multipage, p.auto_multipage),
                         ("consume/in", True, True))
        self.assertEqual((p.preset["resolution"], p.preset["fmt"]), (600, "jpeg"))
        self.assertNotIn("color", p.preset)
        (targets,) = self.service.requested
        self.assertEqual([t.name for t in targets], ["scan1", "paperless"])
        self.assertEqual(targets[0].outdir, self.dir / "scans" / "scan1")
        self.assertEqual(targets[1].outdir, self.dir / "scans" / "consume" / "in")
        self.assertEqual(targets[1].multipage, frozenset({"document", "auto"}))
        self.assertEqual(targets[0].multipage, frozenset())

    def test_save_keeps_other_keys_and_deletes(self):
        self.config_path.parent.mkdir()
        self.config_path.write_text(
            '# comment\nprinter = "192.168.1.50"\noutput = "/scans"\ninterval = 2\n'
            'multipage = "document"\n\n[defaults]\nsize = "a4"\n\n'
            '[[target]]\nname = "scan1"\n\n'
            '[[target]]\nname = "paperless"\noutput = "/consume"\n')
        self.logged_in()
        data = self.client.request("GET", "/targets")[2]
        self.assertIn('value="scan1"', data)
        self.assertIn("<h2>paperless</h2>", data)
        self.assertNotIn("<legend", data)
        # simulate a manual edit between page load and save
        self.config_path.write_text(self.config_path.read_text().replace(
            'printer = "192.168.1.50"', 'printer = "192.168.1.77"'))
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf,
            {"name": "scan1", "existing": "1", "orig": "scan1", "docmp": "1"},
            {"existing": "1", "orig": "paperless", "del": "1"},
            {"name": "new one", "docmp": "1"}))
        self.assertEqual(status, 303)
        cfg = load_config(self.config_path)
        self.assertEqual(cfg.printer, "192.168.1.77")
        self.assertEqual((cfg.output, cfg.interval, cfg.multipage, cfg.size),
                         (Path("/scans"), 2.0, "document", "a4"))
        self.assertEqual([t.name for t in cfg.targets], ["scan1", "new one"])

    def test_invalid_name_writes_nothing(self):
        self.logged_in()
        csrf = self.client.csrf()
        for bad in ("Müller", "a.b"):
            status, _, data = self.client.request(
                "POST", "/targets", self.form(csrf, {"name": "ok"}, {"name": bad}))
            self.assertEqual(status, 400)
            self.assertIn("Row 2", data)
            self.assertIn(f'value="{bad}"', data)   # user input kept
            self.assertFalse(self.config_path.exists())
        self.assertEqual(self.service.requested, [])

    def test_duplicates_clashes_and_escaping(self):
        self.logged_in()
        csrf = self.client.csrf()
        status, _, data = self.client.request(
            "POST", "/targets", self.form(csrf, {"name": "a"}, {"name": "a"}))
        self.assertIn("duplicate", data)
        status, _, data = self.client.request(
            "POST", "/targets", self.form(csrf, {"name": "a b"}, {"name": "a_b"}))
        self.assertEqual(status, 400)
        self.assertIn("both use the folder", data)
        status, _, data = self.client.request(
            "POST", "/targets", self.form(csrf, {"name": '"><script>x</script>'}))
        self.assertNotIn("<script>x", data)
        self.assertFalse(self.config_path.exists())
        status, _, data = self.client.request("POST", "/targets", self.form(csrf, {"name": ""}))
        self.assertIn("At least one target", data)


class FolderCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "scans"
        self.base.mkdir()
        self.outside = Path(self.tmp.name) / "outside"
        self.outside.mkdir()

    def test_accepts_plain_relative_paths(self):
        (self.base / "inner").mkdir()
        good = ["a", "a/b", "Paperless Inbox", "ü-x_1.2", "not/yet/existing", "con_x", "a.b"]
        if CAN_SYMLINK:
            (self.base / "link_in").symlink_to(self.base / "inner")
            good += ["link_in", "link_in/sub"]
        for folder in good:
            web.check_web_folder(folder, self.base)

    def test_dot_alone_is_the_output_directory(self):
        web.check_web_folder(".", self.base)

    def test_rejects_escapes(self):
        bad = ["", "/abs", "//net/share", "..", "../x", "a/../../x", "a/..", "a//b",
               "a/", "./a", "./", "a/.", "a\\b", "..\\x", "a\x00b", "a\nb", "a\tb", "a\x7fb",
               "x" * 300]
        if CAN_SYMLINK:
            (self.base / "link_out").symlink_to(self.outside)
            (self.base / "link_base").symlink_to(self.base)
            bad += ["link_out", "link_out/sub", "link_base"]
        for folder in bad:
            with self.assertRaises(ValueError, msg=repr(folder)):
                web.check_web_folder(folder, self.base)

    def test_rejects_windows_tricks(self):
        # Same result on every platform, so Linux CI covers the Windows rules.
        for bad in ("C:x", "C:", "c:/x", "a:b", "a/b:c", "file.txt:stream", "a/b::$DATA",
                    "con", "CON", "aux", "Nul", "prn", "com1", "COM9", "lpt1", "LPT9",
                    "a/con", "a/NUL.txt", "con.tar.gz", "x/com3.log/y", "con .txt",
                    "trailing.", "trailing ", "a./b", "a /b", "a/b.", "a/b ", "...",
                    "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                web.check_web_folder(bad, self.base)

    def test_reserved_lookalikes_are_fine(self):
        for good in ("console", "com", "com10", "lpt", "aux_1", "nulls", "xcon", "a.con"):
            web.check_web_folder(good, self.base)

    def test_relative_base(self):
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        web.check_web_folder("a/b", Path("./scans"))
        with self.assertRaises(ValueError):
            web.check_web_folder("../a", Path("./scans"))


class FolderRestrictionTests(WebTestBase):
    LOCKED = """\
[[target]]
name = "paperless"
output = "/consume"

[[target]]
name = "up"
output = "../elsewhere"

[[target]]
name = "plain"
output = "inbox"
"""

    def form(self, csrf, *rows):
        form = {"csrf": csrf, "rows": str(len(rows))}
        for i, row in enumerate(rows):
            for key, value in row.items():
                form[f"{key}_{i}"] = value
        return form

    def write_locked(self):
        self.config_path.parent.mkdir()
        self.config_path.write_text(self.LOCKED)

    def test_absolute_and_dotdot_rejected(self):
        self.logged_in()
        csrf = self.client.csrf()
        for bad in ("/consume", "../x", "a/../../x", "a\\b", "/etc/cron.d"):
            status, _, data = self.client.request(
                "POST", "/targets", self.form(csrf, {"name": "a", "output": bad}))
            self.assertEqual(status, 400, bad)
            self.assertIn("Row 1", data)
            self.assertFalse(self.config_path.exists())
        self.assertEqual(self.service.requested, [])
        self.assertFalse((self.dir / "scans").exists())   # nothing created

    @needs_symlinks
    def test_symlink_out_of_base_rejected(self):
        (self.dir / "scans").mkdir()
        (self.dir / "outside").mkdir()
        (self.dir / "scans" / "evil").symlink_to(self.dir / "outside")
        self.logged_in()
        csrf = self.client.csrf()
        for row in ({"name": "a", "output": "evil"}, {"name": "evil"}):
            status, _, data = self.client.request("POST", "/targets", self.form(csrf, row))
            self.assertEqual(status, 400, row)
            self.assertIn("outside the output directory", data)
        self.assertFalse(self.config_path.exists())

    def test_locked_rows_shown_read_only(self):
        self.write_locked()
        self.logged_in()
        data = self.client.request("GET", "/targets")[2]
        self.assertIn("<code>/consume</code>", data)
        self.assertIn("<code>../elsewhere</code>", data)
        self.assertIn("set in the config file", data)
        for field in ("name", "output", "res", "docmp"):
            self.assertNotIn(f'name="{field}_0"', data)
            self.assertNotIn(f'name="{field}_1"', data)
        self.assertIn('name="del_0"', data)
        self.assertIn('name="output_2" value="inbox"', data)
        self.assertNotIn('name="output_3"', data)                # no spare rows

    def ops_form(self, csrf, op, *rows):
        form = self.form(csrf, *rows)
        form["op"] = op
        return form

    def test_locked_target_survives_move_and_save(self):
        self.write_locked()
        before = load_config(self.config_path).targets
        self.logged_in()
        csrf = self.client.csrf()
        rows = ({"existing": "1", "orig": "paperless"}, {"existing": "1", "orig": "up"},
                {"name": "plain", "existing": "1", "orig": "plain", "output": "inbox"})
        status, _, data = self.client.request("POST", "/targets", self.ops_form(
            csrf, "down_0", *rows))
        self.assertEqual(status, 200)
        self.assertIn('name="orig_0" value="up"', data)
        self.assertIn('name="orig_1" value="paperless"', data)
        self.assertIn('data-dirty="1"', data)
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf, {"existing": "1", "orig": "up"}, {"existing": "1", "orig": "paperless"},
            {"name": "plain", "existing": "1", "orig": "plain", "output": "inbox"}))
        self.assertEqual(status, 303)
        after = load_config(self.config_path).targets
        self.assertEqual([t.name for t in after], ["up", "paperless", "plain"])
        self.assertEqual(after[0], before[1])
        self.assertEqual(after[1], before[0])

    def test_locked_rows_kept_whatever_the_form_says(self):
        self.write_locked()
        before = load_config(self.config_path).targets
        self.logged_in()
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf,
            {"name": "paperless", "existing": "1", "orig": "paperless", "output": "/etc"},
            {"name": "renamed", "existing": "1", "orig": "up", "output": "x", "res": "600",
             "docmp": "1"},
            {"name": "plain", "existing": "1", "orig": "plain", "output": "inbox2"}))
        self.assertEqual(status, 303)
        cfg = load_config(self.config_path)
        self.assertEqual(cfg.targets[:2], before[:2])
        self.assertEqual([(t.name, t.output) for t in cfg.targets],
                         [("paperless", "/consume"), ("up", "../elsewhere"),
                          ("plain", "inbox2")])
        # deleting a read-only target is allowed
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf, {"existing": "1", "orig": "paperless", "del": "1"},
            {"existing": "1", "orig": "up"}, {"name": "plain"}))
        self.assertEqual(status, 303)
        self.assertEqual([t.name for t in load_config(self.config_path).targets], ["up", "plain"])

    def test_new_row_cannot_take_a_locked_name(self):
        self.write_locked()
        self.logged_in()
        csrf = self.client.csrf()
        status, _, data = self.client.request("POST", "/targets", self.form(
            csrf, {"name": "up"}, {"existing": "1", "orig": "up"}))
        self.assertEqual(status, 400)
        self.assertIn("duplicate", data)

    def test_forged_orig_cannot_copy_a_locked_folder(self):
        self.write_locked()
        self.logged_in()
        csrf = self.client.csrf()
        # The second claim on "paperless" is an ordinary row: its folder is checked.
        status, _, data = self.client.request("POST", "/targets", self.form(
            csrf,
            {"name": "paperless", "existing": "1", "orig": "paperless"},
            {"name": "copy", "existing": "1", "orig": "paperless", "output": "/consume"}))
        self.assertEqual(status, 400)
        self.assertIn("Row 2", data)
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf,
            {"name": "paperless", "existing": "1", "orig": "paperless", "del": "1"},
            {"name": "copy", "existing": "1", "orig": "paperless"}))
        self.assertEqual(status, 303)
        cfg = load_config(self.config_path)
        self.assertEqual([(t.name, t.output) for t in cfg.targets], [("copy", None)])
        # Without the "existing" flag an orig is ignored as well.
        self.config_path.write_text(self.LOCKED)
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf, {"name": "new", "orig": "paperless"}))
        self.assertEqual(status, 303)
        self.assertEqual([(t.name, t.output) for t in load_config(self.config_path).targets],
                         [("new", None)])

    @needs_symlinks
    def test_locked_default_folder_is_kept(self):
        (self.dir / "scans").mkdir()
        (self.dir / "outside").mkdir()
        (self.dir / "scans" / "evil").symlink_to(self.dir / "outside")
        self.config_path.parent.mkdir()
        self.config_path.write_text('[[target]]\nname = "evil"\n')
        self.logged_in()
        self.assertIn("(default: evil)", self.client.request("GET", "/targets")[2])
        csrf = self.client.csrf()
        status, _, _ = self.client.request("POST", "/targets", self.form(
            csrf, {"name": "other", "existing": "1", "orig": "evil"}))
        self.assertEqual(status, 303)
        self.assertEqual([(t.name, t.output) for t in load_config(self.config_path).targets],
                         [("evil", None)])

    def test_error_rerender_keeps_locked_display(self):
        self.write_locked()
        self.logged_in()
        csrf = self.client.csrf()
        status, _, data = self.client.request("POST", "/targets", self.form(
            csrf,
            {"name": "paperless", "existing": "1", "orig": "paperless"},
            {"name": "bad", "output": "/abs"}))
        self.assertEqual(status, 400)
        self.assertIn("<code>/consume</code>", data)
        self.assertNotIn('name="output_0"', data)
        self.assertNotIn('name="name_0"', data)
        self.assertIn('name="output_1" value="/abs"', data)


class SettingsTests(WebTestBase):
    BASE = {"resolution": "", "color": "", "format": "", "source": "", "size": "",
            "trim_left": "", "trim_top": "", "trim_right": "", "trim_bottom": "",
            "adf_trim_left": "", "adf_trim_top": "", "adf_trim_right": "",
            "adf_trim_bottom": "", "interval": ""}

    def post(self, **values):
        csrf = self.client.csrf("/settings")
        form = {**self.BASE, **values, "csrf": csrf}
        return self.client.request("POST", "/settings", form)

    def test_page_fields_and_read_only_values(self):
        self.logged_in()
        status, _, page = self.client.request("GET", "/settings")
        self.assertEqual(status, 200)
        for name in ("resolution", "color", "format", "source", "size", "trim_left",
                     "trim_top", "trim_right", "trim_bottom", "adf_trim_left",
                     "adf_trim_top", "adf_trim_right", "adf_trim_bottom", "multipage_document",
                     "multipage_auto", "interval",
                     "ignore_panel"):
            self.assertIn(f'name="{name}"', page)
        self.assertNotIn('name="printer"', page)
        self.assertNotIn('name="output"', page)
        self.assertIn("192.0.2.1", page)                 # shown read-only
        self.assertIn(str(self.dir / "scans"), page)
        self.assertIn('href="/config"', page)
        self.assertIn("Edit config.toml directly", page)
        self.assertIn("data-warn-unsaved", page)
        self.assertIn('id="unsaved"', page)
        self.assertIn("Settings</a>", page)

    def test_save_writes_values_and_keeps_the_rest(self):
        self.logged_in()
        self.config_path.parent.mkdir()
        self.config_path.write_text('printer = "10.0.0.9"\nverbose = true\n\n'
                                    '[[target]]\nname = "a"\noutput = "/consume"\n')
        status, resp, _ = self.post(resolution="600", color="gray", format="jpeg",
                                    source="adf", size="letter", trim_right="3",
                                    trim_bottom="2.5", adf_trim_top="1.5",
                                    adf_trim_left="4", multipage_document="1",
                                    multipage_auto="1", interval="2.5",
                                    ignore_panel="1")
        self.assertEqual((status, resp.getheader("Location")), (303, "/settings?saved=1"))
        cfg = load_config(self.config_path)
        self.assertEqual((cfg.resolution, cfg.color, cfg.format, cfg.source, cfg.size),
                         (600, "gray", "jpeg", "adf", "letter"))
        self.assertEqual((cfg.trim_right, cfg.trim_bottom, cfg.trim_left), (3.0, 2.5, None))
        self.assertEqual(cfg.adf_trim(), Trim(left=4, top=1.5))
        self.assertEqual((cfg.multipage, cfg.interval, cfg.ignore_panel), ("both", 2.5, True))
        self.assertEqual((cfg.printer, cfg.verbose), ("10.0.0.9", True))
        self.assertEqual([(t.name, t.output) for t in cfg.targets], [("a", "/consume")])
        self.assertEqual(self.service.requested, [])      # the config watcher applies them
        page = self.client.request("GET", "/settings?saved=1")[2]
        self.assertIn("used from the next poll cycle", page)
        self.assertIn('<option value="600" selected>', page)
        self.assertIn('id="f-ignore_panel" value="1" checked', page)
        self.assertNotIn("used from the next poll cycle",
                         self.client.request("GET", "/settings")[2].split("Source:")[0])

    def test_filename_setting(self):
        self.logged_in()
        self.assertIn('name="filename"', self.client.request("GET", "/settings")[2])
        self.assertEqual(self.post(filename="{name}_{date}")[0], 303)
        self.assertEqual(load_config(self.config_path).filename, "{name}_{date}")
        status, _, page = self.post(filename="{now.__class__}")
        self.assertEqual(status, 400)
        self.assertEqual(load_config(self.config_path).filename, "{name}_{date}")

    def test_empty_values_remove_the_keys(self):
        self.logged_in()
        self.post(resolution="150", trim_left="1")
        self.assertEqual(load_config(self.config_path).resolution, 150)
        self.post()
        cfg = load_config(self.config_path)
        self.assertEqual((cfg.resolution, cfg.trim_left, cfg.ignore_panel), (None, None, None))

    def test_first_save_creates_the_file(self):
        self.logged_in()
        self.assertFalse(self.config_path.exists())
        self.assertEqual(self.post(color="gray")[0], 303)
        self.assertEqual(load_config(self.config_path).color, "gray")
        assert_mode(self, self.config_path, 0o600)

    def test_multipage_boxes(self):
        self.logged_in()
        for boxes, mode in (({}, "off"), ({"multipage_auto": "1"}, "auto"),
                            ({"multipage_document": "1"}, "document")):
            self.post(**boxes)
            self.assertEqual(load_config(self.config_path).multipage, mode, boxes)
        _, _, page = self.client.request("GET", "/settings")
        self.assertIn('name="multipage_document" value="1" checked', page)
        self.assertNotIn('name="multipage_auto" value="1" checked', page)

    def test_validation_errors_write_nothing(self):
        self.logged_in()
        self.post(resolution="300")
        before = self.config_path.read_text()
        for bad in ({"resolution": "123"}, {"resolution": "abc"}, {"color": "blue"},
                    {"format": "tiff"}, {"source": "tray"}, {"size": "a0"},
                    {"trim_left": "51"}, {"trim_top": "-1"}, {"adf_trim_left": "51"},
                    {"adf_trim_top": "abc"},
                    {"trim_right": "abc"}, {"trim_bottom": "nan"}, {"interval": "0"},
                    {"interval": "-3"}, {"interval": "fast"}, {"interval": "inf"}):
            status, _, page = self.post(**bad)
            self.assertEqual(status, 400, bad)
            self.assertIn('class="error bad"', page, bad)
            self.assertEqual(self.config_path.read_text(), before, bad)
        # the bad value is shown again so it can be corrected
        _, _, page = self.post(trim_left="51", interval="7")
        self.assertIn('value="51"', page)
        self.assertIn('value="7"', page)
        self.assertIn("data-dirty", page)
        self.assertIn("0 to 50", page)

    def test_printer_and_output_cannot_be_set(self):
        self.logged_in()
        self.post(color="gray", printer="10.9.9.9", output="/etc")
        cfg = load_config(self.config_path)
        self.assertEqual((cfg.printer, cfg.output), (None, None))

    def test_overrides_are_shown(self):
        self.ctx.overrides = {"interval": "environment variable PUSHSCAN_INTERVAL",
                              "trim_left": "environment variable PUSHSCAN_TRIM",
                              "format": "command line option --format",
                              "printer": "environment variable PUSHSCAN_PRINTER"}
        self.ctx.effective = {"interval": "9", "trim_left": "2", "format": "jpeg"}
        self.logged_in()
        page = self.client.request("GET", "/settings")[2]
        self.assertIn("Overridden by environment variable PUSHSCAN_INTERVAL. In use: "
                      "<code>9</code>", page)
        self.assertIn("Overridden by environment variable PUSHSCAN_TRIM", page)
        self.assertIn("Overridden by command line option --format", page)
        self.assertIn("Overridden by environment variable PUSHSCAN_PRINTER", page)
        self.assertEqual(page.count("Overridden by"), 4)
        self.ctx.overrides = {}
        self.assertNotIn("Overridden by", self.client.request("GET", "/settings")[2])

    def test_targets_page_shows_the_default(self):
        self.ctx.effective = {"resolution": "600", "color": "gray", "format": "jpeg",
                              "size": "letter"}
        self.logged_in()
        page = self.client.request("GET", "/targets")[2]
        for label in ("Default (600 dpi)", "Default (jpeg)", "Default (letter)"):
            self.assertIn(f">{label}</option>", page)
        self.assertNotIn("keep default", page)
        self.assertNotIn("color_0", page)
        self.assertIn('href="/settings"', page)
        self.ctx.effective = {}
        self.assertIn(">Default (300 dpi)</option>", self.client.request("GET", "/targets")[2])

    def test_csrf_and_origin(self):
        self.logged_in()
        for form in ({}, {"csrf": "wrong"}):
            self.assertEqual(self.client.request("POST", "/settings", form)[0], 403)
        csrf = self.client.csrf("/settings")
        status, _, _ = self.client.request("POST", "/settings", {"csrf": csrf, "color": "gray"},
                                           headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertFalse(self.config_path.exists())

    def test_needs_login_and_config_path(self):
        self.assertEqual(self.client.request("GET", "/settings")[0], 303)
        self.assertEqual(self.client.request("GET", "/config")[0], 303)
        self.ctx.config_path = None
        self.logged_in()
        status, _, page = self.client.request("GET", "/settings")
        self.assertEqual(status, 200)
        self.assertIn("No config file is known", page)
        csrf = self.client.csrf("/settings")
        self.assertEqual(self.client.request("POST", "/settings",
                                             {"csrf": csrf, "color": "gray"})[0], 403)
        self.assertEqual(self.client.request("POST", "/config",
                                             {"csrf": csrf, "text": "", "hash": ""})[0], 403)


class RawConfigTests(WebTestBase):
    START = ('# my comment\nprinter = "192.0.2.1"\n\n[defaults]\nresolution = 300  # dpi\n\n'
             '[[target]]\nname = "plain"\noutput = "inbox"\n\n'
             '[[target]]\nname = "paperless"\noutput = "/consume"\n')

    def setUp(self):
        super().setUp()
        self.config_path.parent.mkdir()
        self.config_path.write_text(self.START)
        self.logged_in()

    def page_hash(self):
        page = self.client.request("GET", "/config")[2]
        match = re.search(r'name="hash" value="([0-9a-f]*)"', page)
        return match.group(1)

    def save(self, text, digest=None):
        csrf = self.client.csrf("/config")
        form = {"csrf": csrf, "text": text,
                "hash": self.page_hash() if digest is None else digest}
        return self.client.request("POST", "/config", form)

    def assertRejected(self, text, fragment, status=400):
        before = self.config_path.read_text()
        code, _, page = self.save(text)
        self.assertEqual(code, status, page)
        self.assertIn(fragment, html.unescape(page))
        self.assertEqual(self.config_path.read_text(), before)
        self.assertEqual(self.service.requested, [])
        return page

    def test_page(self):
        status, _, page = self.client.request("GET", "/config")
        self.assertEqual(status, 200)
        self.assertIn("<textarea", page)
        self.assertIn('spellcheck="false"', page)
        self.assertIn('rows="30"', page)
        self.assertIn("data-tab-indent", page)
        self.assertIn("data-warn-unsaved", page)
        self.assertIn("# my comment", page)
        self.assertIn('printer = &quot;192.0.2.1&quot;', page)     # escaped
        self.assertIn("drop comments", page)
        self.assertIn('<script src="/app.js" defer></script>', page)
        self.assertIn('href="/settings"', page)

    def test_text_is_escaped(self):
        self.config_path.write_text("# </textarea><b>x</b>\n")
        page = self.client.request("GET", "/config")[2]
        self.assertNotIn("<b>x</b>", page)
        self.assertIn("&lt;/textarea&gt;", page)

    def test_accept_keeps_comments_and_applies_targets(self):
        text = self.START.replace("300  # dpi", "600  # sharper") + "# more\n"
        text = text.replace('name = "plain"', 'name = "plain2"')
        status, resp, _ = self.save(text.replace("\n", "\r\n"))   # as a browser sends it
        self.assertEqual((status, resp.getheader("Location")), (303, "/config?saved=1"))
        self.assertEqual(self.config_path.read_text(), text)       # verbatim, LF
        assert_mode(self, self.config_path, 0o644)
        self.assertEqual(len(self.service.requested), 1)
        names = [t.name for t in self.service.requested[0]]
        self.assertEqual(names, ["plain2", "paperless"])
        self.assertIn("Saved.", self.client.request("GET", "/config?saved=1")[2])

    def test_second_save_with_new_hash(self):
        self.assertEqual(self.save(self.START + "# a\n")[0], 303)
        self.assertEqual(self.save(self.START + "# b\n")[0], 303)

    def test_invalid_toml_shows_line_and_text(self):
        text = 'printer = "192.0.2.1"\ninterval = \n# my edit\n'
        page = self.assertRejected(text, "line 2")
        self.assertIn("# my edit", page)
        self.assertIn("data-dirty", page)

    def test_invalid_values_rejected(self):
        self.assertRejected('[defaults]\nresolution = 100\n', "resolution")
        self.assertRejected('foo = 1\n', 'unknown key "foo"')

    def test_non_ascii_text_round_trips(self):
        self.assertEqual(self.save('printer = "192.0.2.1"\n# caf\u00e9 \u2603\n')[0], 303)
        self.assertIn("\u2603", self.client.request("GET", "/config")[2])

    def test_output_change_rejected(self):
        self.assertRejected('output = "/etc"\n' + self.START, '"output" cannot be changed')
        self.config_path.write_text('output = "/scans"\n' + self.START)
        self.assertRejected(self.START, '"output" cannot be changed')       # removal
        self.assertRejected('output = "/other"\n' + self.START, '"output" cannot')
        # unchanged is fine
        self.assertEqual(self.save('output = "/scans"\n' + self.START + "# x\n")[0], 303)

    def test_output_equal_to_the_one_in_use_is_accepted(self):
        text = f'output = "{(self.dir / "scans").as_posix()}"\n' + self.START
        self.assertEqual(self.save(text)[0], 303)

    def test_printer_change_rejected(self):
        self.assertRejected(self.START.replace("192.0.2.1", "10.9.9.9"),
                            '"printer" cannot be changed')
        self.assertRejected(self.START.replace('printer = "192.0.2.1"\n', ""),
                            '"printer" cannot be changed')                   # removal

    def test_target_folder_outside_output_rejected(self):
        for output in ("/etc", "../up", "a/../../b", "a\\\\b"):
            text = self.START + f'\n[[target]]\nname = "evil"\noutput = "{output}"\n'
            self.assertRejected(text, 'Target "evil"')

    @needs_symlinks
    def test_target_symlink_out_of_output_rejected(self):
        (self.dir / "scans").mkdir()
        (self.dir / "scans" / "link").symlink_to(self.dir)
        text = self.START + '\n[[target]]\nname = "evil"\noutput = "link"\n'
        self.assertRejected(text, 'Target "evil"')

    @needs_symlinks
    def test_target_default_folder_is_checked_too(self):
        (self.dir / "scans").mkdir()
        (self.dir / "scans" / "evil").symlink_to(self.dir)   # safe_dirname("evil")
        self.assertRejected(self.START + '\n[[target]]\nname = "evil"\n', 'Target "evil"')

    def test_web_table_cannot_be_changed(self):
        for extra in ('\n[web]\nenabled = true\n', '\n[web]\nbind = "0.0.0.0"\n',
                      '\n[web]\npassword_file = "known.txt"\n'):
            self.assertRejected(self.START + extra, "The [web] table cannot be changed")

    def test_unchanged_locked_target_is_accepted(self):
        text = self.START.replace('output = "inbox"', 'output = "inbox2"') + "# edit\n"
        self.assertEqual(self.save(text)[0], 303)
        self.assertIn('output = "/consume"', self.config_path.read_text())
        self.assertEqual([t.outdir for t in self.service.requested[0]],
                         [self.dir / "scans" / "inbox2", self.dir / "scans" / "/consume"])   # Windows: drive of the base

    def test_locked_target_changes_rejected(self):
        self.assertRejected(self.START.replace("/consume", "/etc"), 'Target "paperless"')
        self.assertRejected(self.START.replace('name = "paperless"', 'name = "other"'),
                            'Target "other"')
        # another target cannot take over the locked folder
        text = self.START + '\n[[target]]\nname = "copy"\noutput = "/consume"\n'
        self.assertRejected(text, 'Target "copy"')

    def test_deleting_a_locked_target_is_fine(self):
        text = self.START.split('[[target]]\nname = "paperless"')[0]
        self.assertEqual(self.save(text)[0], 303)

    def test_stale_hash_refused(self):
        digest = self.page_hash()
        changed = self.START + "# changed by someone else\n"
        self.config_path.write_text(changed)
        status, _, page = self.save(self.START + "# my edit\n", digest)
        self.assertEqual(status, 409)
        self.assertIn("changed on disk", page)
        self.assertIn("# changed by someone else", page)
        self.assertNotIn("# my edit", page)
        self.assertEqual(self.config_path.read_text(), changed)
        self.assertEqual(self.service.requested, [])
        # the page now carries the new hash, so saving works
        new_digest = re.search(r'name="hash" value="([0-9a-f]*)"', page).group(1)
        self.assertEqual(self.save(changed + "# mine\n", new_digest)[0], 303)

    def test_missing_hash_is_stale(self):
        self.assertEqual(self.save(self.START, "")[0], 409)

    def test_creates_a_missing_file(self):
        self.config_path.unlink()
        page = self.client.request("GET", "/config")[2]
        self.assertIn("does not exist yet", page)
        self.assertEqual(self.save('[defaults]\ncolor = "gray"\n')[0], 303)
        self.assertEqual(load_config(self.config_path).color, "gray")
        assert_mode(self, self.config_path, 0o600)

    def test_no_targets_in_text_leaves_the_service_alone(self):
        self.assertEqual(self.save('printer = "192.0.2.1"\n[defaults]\ncolor = "gray"\n')[0], 303)
        self.assertEqual(self.service.requested, [])

    def test_targets_from_env_not_applied(self):
        self.ctx.targets_from_env = True
        self.assertEqual(self.save(self.START + "# x\n")[0], 303)
        self.assertEqual(self.service.requested, [])

    def test_unreadable_file(self):
        self.config_path.write_bytes(b"\xff\xfe")
        status, _, page = self.client.request("GET", "/config")
        self.assertEqual(status, 200)
        self.assertIn("Cannot read the config file", page)
        self.assertNotIn("<textarea", page)

    def test_csrf_origin_and_size(self):
        csrf = self.client.csrf("/config")
        digest = self.page_hash()
        for form in ({}, {"csrf": "wrong", "text": "", "hash": digest}):
            self.assertEqual(self.client.request("POST", "/config", form)[0], 403)
        status, _, _ = self.client.request(
            "POST", "/config", {"csrf": csrf, "text": self.START + "# x\n", "hash": digest},
            headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.config_path.read_text(), self.START)
        status, _, _ = self.client.request(
            "POST", "/config", {"csrf": csrf, "hash": digest, "text": "#" * (70 * 1024)})
        self.assertEqual(status, 413)
        self.assertEqual(self.config_path.read_text(), self.START)

    def test_no_inline_script_on_new_pages(self):
        for path in ("/settings", "/config"):
            page = self.client.request("GET", path)[2].lower()
            self.assertFalse(re.search(r"<script(?![^>]*\ssrc=)", page), path)
            self.assertIsNone(re.search(r"<[^>]+\son[a-z]+\s*=", page), path)
            self.assertNotIn("javascript:", page)
            self.assertIn('<script src="/app.js" defer></script>', page)

    def test_js_is_generic(self):
        js = self.client.request("GET", "/app.js")[2]
        self.assertIn("form[data-warn-unsaved]", js)
        self.assertIn("textarea[data-tab-indent]", js)
        self.assertNotIn("targets-form", js)


class SessionTests(WebTestBase):
    def test_cookie_max_age_is_absolute_lifetime(self):
        _, resp, _ = self.client.login()
        self.assertIn(f"Max-Age={web.SESSION_MAX_SECONDS}", resp.getheader("Set-Cookie"))
        self.assertNotIn("Secure", resp.getheader("Set-Cookie"))

    def test_absolute_lifetime(self):
        clock = [1000.0]
        with mock.patch.object(web, "_now", lambda: clock[0]):
            self.logged_in()
            step = web.SESSION_IDLE_SECONDS / 2
            while clock[0] + step < 1000.0 + web.SESSION_MAX_SECONDS:
                clock[0] += step
                self.assertEqual(self.client.request("GET", "/")[0], 200)
            clock[0] = 1000.0 + web.SESSION_MAX_SECONDS + 1
            self.assertEqual(self.client.request("GET", "/")[0], 303)

    def test_session_limit_drops_oldest(self):
        clock = [1000.0]
        port = self.server.server_address[1]
        with mock.patch.object(web, "_now", lambda: clock[0]):
            clients = []
            for _ in range(web.MAX_SESSIONS + 1):
                clock[0] += 1
                c = Client(port)
                self.assertEqual(c.login()[0], 303)
                clients.append(c)
            self.assertEqual(len(self.server.sessions), web.MAX_SESSIONS)
            self.assertEqual(clients[0].request("GET", "/")[0], 303)
            self.assertEqual(clients[1].request("GET", "/")[0], 200)
            self.assertEqual(clients[-1].request("GET", "/")[0], 200)

    def test_login_replaces_the_old_session(self):
        self.logged_in()
        old = self.client.cookie
        self.logged_in()
        self.assertNotEqual(old, self.client.cookie)
        stale = Client(self.server.server_address[1])
        stale.cookie = old
        self.assertEqual(stale.request("GET", "/")[0], 303)
        self.assertEqual(self.client.request("GET", "/")[0], 200)

    def test_only_token_hashes_are_stored_and_nothing_is_logged(self):
        with self.assertLogs("pushscan2folder.web", logging.DEBUG) as logs:
            self.logged_in()
            self.client.request("GET", "/?x=1")
            self.client.login("wrong password")
        token = self.client.cookie.split("=", 1)[1]
        self.assertNotIn(token, repr(self.server.sessions.__dict__))
        self.assertNotIn(token, "\n".join(logs.output))
        self.assertNotIn(PASSWORD, "\n".join(logs.output))
        self.assertNotIn("wrong password", "\n".join(logs.output))
        self.assertFalse(hasattr(self.server, "password"))
        self.assertNotIn(PASSWORD, repr(self.server.__dict__))

    def test_lockout_escalates_and_resets(self):
        clock = [1000.0]
        with mock.patch.object(web, "_now", lambda: clock[0]):
            for _ in range(5):
                self.client.login("wrong wrong")
            clock[0] += web.LOCKOUT_SECONDS + 1
            for _ in range(5):
                self.assertEqual(self.client.login("wrong wrong")[0], 401)
            clock[0] += web.LOCKOUT_SECONDS + 1          # second lockout is twice as long
            self.assertEqual(self.client.login()[0], 429)
            clock[0] += web.LOCKOUT_SECONDS
            self.assertEqual(self.client.login()[0], 303)
            for _ in range(5):                           # reset: back to the short lockout
                self.client.login("wrong wrong")
            clock[0] += web.LOCKOUT_SECONDS + 1
            self.assertEqual(self.client.login()[0], 303)

    def test_lockout_is_capped(self):
        clock = [1000.0]
        with mock.patch.object(web, "_now", lambda: clock[0]):
            for _ in range(20):
                for _ in range(5):
                    self.client.login("wrong wrong")
                clock[0] += web.MAX_LOCKOUT_SECONDS + 1
            self.assertEqual(self.client.login()[0], 303)

    def test_concurrent_attempts_cannot_exceed_the_limit(self):
        calls = []
        sessions = web.Sessions()

        def wrong():
            calls.append(1)
            return False

        threads = [threading.Thread(target=lambda: self._attempt(sessions, wrong))
                   for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(calls), web.MAX_FAILURES)

    @staticmethod
    def _attempt(sessions, check):
        try:
            sessions.login(check)
        except PermissionError:
            pass


class SecureCookieTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ctx = web.WebContext(FakeService(), LogBuffer(), "192.0.2.1", Path(self.tmp.name),
                             config_path=Path(self.tmp.name) / "c.toml")
        self.server, thread = web.start_server(ctx, PASSWORD, "127.0.0.1", 0,
                                               secure_cookie=True)
        self.addCleanup(web.stop_server, self.server, thread)
        self.port = self.server.server_address[1]

    def test_host_prefix_and_secure(self):
        client = Client(self.port, cookie_name=web.SECURE_COOKIE)
        self.assertEqual(client.login()[0], 303)
        cookie = client.last_set_cookie
        self.assertTrue(cookie.startswith("__Host-p2f_session="))
        for flag in ("; Secure", "; HttpOnly", "; SameSite=Strict", "; Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Domain", cookie)
        self.assertEqual(client.request("GET", "/")[0], 200)
        # the plain name is not accepted
        plain = Client(self.port)
        plain.cookie = web.COOKIE + "=" + client.cookie.split("=", 1)[1]
        self.assertEqual(plain.request("GET", "/")[0], 303)
        csrf = client.csrf("/")
        _, resp, _ = client.request("POST", "/logout", {"csrf": csrf})
        out = resp.getheader("Set-Cookie")
        self.assertTrue(out.startswith("__Host-p2f_session=;"))
        self.assertIn("Max-Age=0", out)
        self.assertIn("; Secure", out)

    def test_env_switch(self):
        with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_SECURE_COOKIE": "1"}):
            self.assertTrue(cli.env_bool("WEB_SECURE_COOKIE", False))


class RawHttpTests(WebTestBase):
    def raw(self, data: bytes, timeout=5) -> bytes:
        """Send raw bytes, read until the server closes the connection."""
        with socket.create_connection(("127.0.0.1", self.server.server_address[1]),
                                      timeout=timeout) as sock:
            sock.sendall(data)
            out = b""
            while True:
                try:
                    chunk = sock.recv(65536)
                except (ConnectionResetError, ConnectionAbortedError):   # macOS, Windows
                    return out
                if not chunk:
                    return out
                out += chunk

    def test_bad_content_length(self):
        for value in ("²".encode("latin-1"), b"-1", b"1e3", b"0x10", b"abc"):
            out = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: " + value
                           + b"\r\n\r\n")
            self.assertTrue(out.startswith(b"HTTP/1.1 400"), (value, out[:40]))

    def test_transfer_encoding_and_duplicate_length_refused(self):
        out = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n"
                       b"Content-Length: 4\r\n\r\n0\r\n\r\nGET /style.css HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"))
        self.assertEqual(out.count(b"HTTP/1.1 "), 1)
        out = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: 3\r\n"
                       b"Content-Length: 40\r\n\r\na=b")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"))

    def test_get_with_body_closes_connection(self):
        smuggled = b"GET /style.css HTTP/1.1\r\nHost: x\r\n\r\n"
        out = self.raw(b"GET /login HTTP/1.1\r\nHost: x\r\nContent-Length: "
                       + str(len(smuggled)).encode() + b"\r\n\r\n" + smuggled)
        self.assertTrue(out.startswith(b"HTTP/1.1 200"))
        self.assertEqual(out.count(b"HTTP/1.1 "), 1)
        self.assertIn(b"Connection: close", out)

    def test_413_closes_connection(self):
        body = b"a" * (web.MAX_BODY + 10)
        out = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: "
                       + str(len(body)).encode() + b"\r\n\r\n" + body
                       + b"GET /style.css HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 413"))
        self.assertEqual(out.count(b"HTTP/1.1 "), 1)

    def test_keep_alive_still_works(self):
        req = b"GET /style.css HTTP/1.1\r\nHost: x\r\n\r\n"
        out = self.raw(req + req + b"GET /style.css HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertEqual(out.count(b"HTTP/1.1 200"), 3)

    def test_too_many_fields(self):
        status, _, _ = self.client.request("POST", "/login", raw=b"&".join(
            b"f%d=1" % i for i in range(3000)), headers={
            "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 400)

    def test_origin_null_and_cross_site_fetch(self):
        for headers in ({"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Origin": "http://127.0.0.1.evil.example"}):
            status, _, _ = self.client.request("POST", "/login", {"password": PASSWORD},
                                               headers=headers)
            self.assertEqual(status, 403, headers)
        status, _, _ = self.client.request("POST", "/login", {"password": PASSWORD},
                                           headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 303)

    def test_browser_post_with_null_origin_from_same_site(self):
        # What a browser sent behind a Docker port mapping (8021 -> 8080).
        status, _, _ = self.client.request("POST", "/login", {"password": PASSWORD}, headers={
            "Origin": "null", "Sec-Fetch-Site": "same-origin", "Host": "192.168.1.5:8021"})
        self.assertEqual(status, 303)

    def test_referrer_policy_keeps_origin(self):
        _, resp, _ = self.client.request("GET", "/login")
        self.assertEqual(resp.getheader("Referrer-Policy"), "same-origin")

    def test_slow_client_is_dropped(self):
        self.server.RequestHandlerClass = type("Fast", (web.Handler,), {"timeout": 0.3})
        started = time.monotonic()
        out = self.raw(b"GET / HTTP/1.1\r\nHost: x\r\n", timeout=5)   # never finished
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(out, b"")

    def test_connection_limit(self):
        self.server._slots = threading.BoundedSemaphore(1)
        port = self.server.server_address[1]
        hold = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            hold.sendall(b"GET / HTTP/1.1\r\n")     # occupies the only slot
            time.sleep(0.3)
            self.assertEqual(self.raw(b"GET /style.css HTTP/1.1\r\nHost: x\r\n\r\n"), b"")
        finally:
            hold.close()
        for _ in range(50):                          # slot is released after the close
            out = self.raw(b"GET /style.css HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            if out:
                break
            time.sleep(0.1)
        self.assertTrue(out.startswith(b"HTTP/1.1 200"))

    def test_log_lines_escape_control_characters(self):
        self.assertEqual(web._printable("GET /\r\nX: y"), "GET /\\x0d\\x0aX: y")


class ConfigWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def roundtrip(self, cfg):
        path = self.dir / "c.toml"
        write_config(path, dump_config(cfg))
        return load_config(path)

    def test_roundtrip_example(self):
        cfg = load_config(EXAMPLE)
        self.assertEqual(self.roundtrip(cfg), cfg)

    def test_roundtrip_edge_cases(self):
        cfg = Config(printer='pr"in\\ter', output=Path("/a b/c"), interval=0.5, verbose=True,
                     targets=[TargetSpec("x", output='dir "q" \\ \t\u0001\u007f ü',
                                         preset={"resolution": 75, "width": 1181,
                                                 "height": 1772},
                                         document_multipage=False, auto_multipage=True),
                              TargetSpec("y", auto_multipage=False)])
        self.assertEqual(self.roundtrip(cfg), cfg)
        self.assertEqual(self.roundtrip(Config()), Config())

    def test_new_file_is_private(self):
        path = self.dir / "sub" / "c.toml"
        write_config(path, "x = 1\n")
        assert_mode(self, path, 0o600)

    def test_atomic_write_keeps_mode_and_leaves_no_temp(self):
        path = self.dir / "c.toml"
        path.write_text("old")
        path.chmod(0o640)
        write_config(path, "new")
        self.assertEqual(path.read_text(), "new")
        assert_mode(self, path, 0o640)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["c.toml"])

    def test_busy_fallback_writes_in_place(self):
        path = self.dir / "c.toml"
        path.write_text("old")
        inode = path.stat().st_ino
        for code in (errno.EBUSY, errno.EXDEV, errno.EPERM):
            with mock.patch("os.replace", side_effect=OSError(code, "nope")):
                write_config(path, f"new {code}")
            self.assertEqual(path.read_text(), f"new {code}")
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual([p.name for p in self.dir.iterdir()], ["c.toml"])

    def test_other_errors_propagate(self):
        path = self.dir / "c.toml"
        path.write_text("old")
        with mock.patch("os.replace", side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                write_config(path, "new")
        self.assertEqual(path.read_text(), "old")


class MainTests(unittest.TestCase):
    def run_main(self, argv, **env):
        keep = {k: v for k, v in os.environ.items() if not k.startswith("PUSHSCAN_")}
        keep["PUSHSCAN_WEB_PORT"] = "0"   # never the real port if a server starts
        keep.update(env)
        with mock.patch.dict(os.environ, keep, clear=True), \
                mock.patch("sys.stderr"):
            return cli.main(argv)

    def test_password_missing_or_short(self):
        self.assertEqual(self.run_main(["--printer", "192.0.2.1", "run", "--web",
                                        "--web-bind", "0.0.0.0"]), 2)
        self.assertEqual(self.run_main(["--printer", "192.0.2.1", "run", "--web",
                                        "--web-bind", "192.168.1.5"]), 2)
        self.assertEqual(self.run_main(["--printer", "192.0.2.1", "run"],
                                       PUSHSCAN_WEB="1", PUSHSCAN_WEB_PASSWORD="short"), 2)

    def test_password_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "pw"
            f.write_text("longenough\n")
            with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD_FILE": str(f)}):
                self.assertEqual(cli.read_web_password(), "longenough")
            f.write_text("short\n")
            with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD_FILE": str(f)}):
                with self.assertRaises(ValueError):
                    cli.read_web_password()

    def test_password_check_off(self):
        env = {"PUSHSCAN_WEB_PASSWORD": "short", "PUSHSCAN_WEB_PASSWORD_CHECK": "0"}
        with mock.patch.dict(os.environ, env), self.assertLogs(level="WARNING") as logs:
            self.assertEqual(cli.web_password_setup(), "short")
        self.assertIn("PUSHSCAN_WEB_PASSWORD_CHECK=0", logs.output[0])
        env["PUSHSCAN_WEB_PASSWORD"] = cli.EXAMPLE_PASSWORD
        with mock.patch.dict(os.environ, env), self.assertLogs(level="WARNING"):
            self.assertEqual(cli.web_password_setup(), cli.EXAMPLE_PASSWORD)
        # an empty password stays an error, and the rules stay on by default
        with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD_CHECK": "0"}):
            with self.assertRaises(ValueError):
                cli.web_password_setup()
        for value in ("short", cli.EXAMPLE_PASSWORD):
            with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_PASSWORD": value}):
                with self.assertRaises(ValueError):
                    cli.web_password_setup()
        # a typo does not switch the rules off
        env["PUSHSCAN_WEB_PASSWORD_CHECK"] = "o"
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(ValueError):
                cli.web_password_setup()

    def test_auth_off(self):
        with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_AUTH": "0"}, clear=True):
            with self.assertNoLogs(level="WARNING"):
                self.assertIsNone(cli.web_password_setup())   # no password needed
        env = {"PUSHSCAN_WEB_AUTH": "0", "PUSHSCAN_WEB_PASSWORD": "short"}
        with mock.patch.dict(os.environ, env), self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(cli.web_password_setup())
        self.assertIn("ignored", logs.output[0])
        with mock.patch.dict(os.environ, {"PUSHSCAN_WEB_AUTH": "maybe"}):
            with self.assertRaises(ValueError):
                cli.web_password_setup()

    def test_main_without_auth_warns(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("pushscan2folder.service.PushScanService.run"), \
                self.assertLogs(level="WARNING") as logs:
            code = self.run_main(
                ["--printer", "192.0.2.1", "--config", str(Path(d) / "c.toml"),
                 "run", "--web", "--web-port", "0", "--web-bind", "0.0.0.0"],
                PUSHSCAN_WEB_AUTH="0", PUSHSCAN_NAME="me")
        self.assertEqual(code, 0)
        self.assertTrue(any("web page without password" in m for m in logs.output))

    def test_web_wired_and_shut_down(self):
        seen = {}

        def fake_run(service):
            seen["ctx_ok"] = True
            seen["handlers"] = [h for h in logging.getLogger().handlers
                                if isinstance(h, LogBuffer)]

        with tempfile.TemporaryDirectory() as d, \
                mock.patch("pushscan2folder.service.PushScanService.run", fake_run), \
                mock.patch("pushscan2folder.web.start_server",
                           wraps=web.start_server) as start:
            code = self.run_main(
                ["--printer", "192.0.2.1", "--config", str(Path(d) / "c.toml"),
                 "run", "--web", "--web-port", "0", "--web-bind", "127.0.0.1"],
                PUSHSCAN_WEB_PASSWORD="longenough", PUSHSCAN_NAME="me")
        self.assertEqual(code, 0)
        self.assertTrue(seen["ctx_ok"])
        self.assertEqual(len(seen["handlers"]), 1)
        self.assertEqual([h for h in logging.getLogger().handlers
                          if isinstance(h, LogBuffer)], [])
        ctx = start.call_args.args[0]
        self.assertFalse(ctx.targets_from_env)


class PrinterSearchTests(WebTestBase):
    def setUp(self):
        super().setUp()
        self.searches = 0
        self.result = [Scanner("192.0.2.7", "Canon TR8500 series", "Canon <TR8500>"),
                       Scanner("192.0.2.1", "Old", "")]

        def discover():
            self.searches += 1
            return list(self.result)
        self.ctx.discover_fn = discover
        write_config(self.config_path, dump_config(Config(printer="192.0.2.1", interval=3.0)))
        self.logged_in()

    def search(self):
        csrf = self.client.csrf("/settings")
        return self.client.request("POST", "/printer/search", {"csrf": csrf})

    def test_settings_page_offers_the_search(self):
        page = self.client.request("GET", "/settings")[2]
        self.assertIn('action="/printer/search"', page)
        self.assertEqual(self.searches, 0)   # only on request

    def test_search_lists_scanners_escaped(self):
        status, _, page = self.search()
        self.assertEqual(status, 200)
        self.assertEqual(self.searches, 1)
        self.assertIn("Canon &lt;TR8500&gt;", page)
        self.assertNotIn("<TR8500>", page)
        self.assertIn('name="address" value="192.0.2.7"', page)
        self.assertNotIn('name="address" value="192.0.2.1"', page)   # the one in use
        self.assertIn("in use", page)

    def test_nothing_found(self):
        self.result = []
        page = self.search()[2]
        self.assertIn("No scanner answered", page)

    def test_use_writes_the_printer_and_keeps_the_rest(self):
        self.search()
        csrf = self.client.csrf("/settings")
        status, resp, _ = self.client.request("POST", "/printer/use",
                                              {"csrf": csrf, "address": "192.0.2.7"})
        self.assertEqual(status, 303)
        cfg = load_config(self.config_path)
        self.assertEqual((cfg.printer, cfg.interval), ("192.0.2.7", 3.0))
        page = self.client.request("GET", resp.getheader("Location"))[2]
        self.assertIn("The printer 192.0.2.7 is used from the next poll cycle", page)

    def test_only_found_addresses_are_accepted(self):
        self.search()
        csrf = self.client.csrf("/settings")
        for address in ("10.0.0.1", "", "192.0.2.7 "):
            status, _, page = self.client.request("POST", "/printer/use",
                                                  {"csrf": csrf, "address": address + "x"})
            self.assertEqual(status, 400)
            self.assertIn("Only an address found by the search", page)
        self.assertEqual(load_config(self.config_path).printer, "192.0.2.1")

    def test_use_without_a_search_is_refused(self):
        csrf = self.client.csrf("/settings")
        status, _, _ = self.client.request("POST", "/printer/use",
                                           {"csrf": csrf, "address": "192.0.2.7"})
        self.assertEqual(status, 400)

    def test_csrf_is_required(self):
        for path in ("/printer/search", "/printer/use"):
            status, _, _ = self.client.request("POST", path, {"csrf": "wrong",
                                                              "address": "192.0.2.7"})
            self.assertEqual(status, 403)
        self.assertEqual(self.searches, 0)

    def test_one_search_at_a_time(self):
        self.server.search_lock.acquire()
        try:
            status, _, page = self.search()
        finally:
            self.server.search_lock.release()
        self.assertEqual(status, 409)
        self.assertIn("already running", page)
        self.assertEqual(self.searches, 0)

    def test_overridden_printer_has_no_search(self):
        self.ctx.overrides["printer"] = "environment variable PUSHSCAN_PRINTER"
        page = self.client.request("GET", "/settings")[2]
        self.assertNotIn("/printer/search", page)
        self.assertIn("PUSHSCAN_PRINTER", page)
        csrf = self.client.csrf("/settings")
        self.assertEqual(self.client.request("POST", "/printer/search", {"csrf": csrf})[0], 404)

    def test_without_search_function(self):
        self.ctx.discover_fn = None
        page = self.client.request("GET", "/settings")[2]
        self.assertNotIn("/printer/search", page)
        self.assertIn("Change it in the config file", page)


if __name__ == "__main__":
    unittest.main()
