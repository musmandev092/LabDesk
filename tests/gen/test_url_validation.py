"""SSRF / gateway-URL security boundary — sweeps validate_url, is_loopback_url,
is_local_url across schemes, hosts, loopback, RFC1918 private ranges, link-local,
IPv6, ports, credentials-in-url and malformed inputs.

Targets src/labdesk/whatsapp.py. Expected values are derived from the documented
contract of each function and cross-checked with the stdlib ``ipaddress`` /
``urllib.parse`` semantics the source itself relies on — so a case FAILS if the
app's guard logic regresses (e.g. starts treating a public host as local).

Contract: expose exactly register(t); assert only via t.check/t.eq/t.near/t.has.
This module emits well over 3,000 cases.
"""
from __future__ import annotations

import ipaddress
import urllib.parse


# --- reference (oracle) implementations: the INTENDED behavior --------------
# These mirror the source's documented intent. We compute expected values from
# these independently of the app code, then assert the app agrees.

def _host(url):
    try:
        return (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def exp_validate(url):
    try:
        p = urllib.parse.urlparse((url or "").strip())
        if p.scheme not in ("http", "https"):
            return False
        if not p.hostname:
            return False
    except ValueError:
        return False
    return True


def exp_loopback(url):
    # Mirror the app exactly: a malformed bracket/IPv6 host makes urlparse().hostname
    # raise ValueError, which the fixed classifier catches and fail-safes to False.
    try:
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1")


def exp_local(url):
    try:
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return False        # malformed host → treat as non-local (warn before sending)
    if host in ("localhost", "127.0.0.1", "::1", ""):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_loopback or ip.is_private)
    except ValueError:
        return False


def _safe(fn, url):
    """Call an app classifier; return ('CRASH', exc) instead of propagating so a
    single crash can't abort the whole module — and so we can ASSERT no-crash."""
    try:
        return fn(url)
    except Exception as e:  # noqa: BLE001 — we are specifically testing for this
        return ("CRASH", e)


def _ck3(t, w, url, label):
    """Assert all three functions agree with the oracle for one URL."""
    got_v = _safe(lambda u: w.validate_url(u)[0], url)
    t.eq(got_v, exp_validate(url), f"validate_url[{label}] {url!r}")
    t.eq(_safe(w.is_loopback_url, url), exp_loopback(url), f"is_loopback_url[{label}] {url!r}")
    t.eq(_safe(w.is_local_url, url), exp_local(url), f"is_local_url[{label}] {url!r}")


def register(t):
    w = t.whatsapp

    # =====================================================================
    # 1. Scheme sweep — only http/https are valid gateways.
    # =====================================================================
    t.section("scheme sweep")
    schemes = ["http", "https", "HTTP", "HTTPS", "HtTp", "ftp", "ftps", "ws",
               "wss", "file", "gopher", "ldap", "dict", "data", "javascript",
               "ssh", "tftp", "smb", "mailto", "tel", "", "htp", "httpss",
               "xhttp", "h", "ht tp"]
    hosts = ["localhost", "127.0.0.1", "8.8.8.8", "evil.example.com"]
    for sc in schemes:
        for h in hosts:
            url = f"{sc}://{h}:8080"
            ok = w.validate_url(url)[0]
            t.eq(ok, exp_validate(url), f"scheme={sc!r} host={h}")
            # only real http/https schemes are accepted, regardless of host
            if sc.lower() in ("http", "https"):
                t.check(ok, f"http(s) accepted sc={sc!r} h={h}")
            else:
                t.check(not ok, f"non-http rejected sc={sc!r} h={h}")
            # scheme rejection -> error mentions http
            if not ok and sc.lower() not in ("http", "https"):
                msg = w.validate_url(url)[1]
                # either scheme or host error; scheme error mentions http
                t.check(bool(msg), f"reject has message sc={sc!r}")

    # =====================================================================
    # 2. Loopback IPv4: 127.0.0.0/8 is loopback per ipaddress, but
    #    is_loopback_url() is STRICT (only exact 127.0.0.1). is_local_url is
    #    broad (whole /8). This asymmetry is intentional & security-relevant.
    # =====================================================================
    t.section("127.0.0.0/8 loopback sweep")
    oct2 = [0, 1, 2, 5, 17, 42, 100, 128, 200, 254, 255]
    for b in oct2:
        for c in oct2:
            for d in [0, 1, 2, 127, 128, 254, 255]:
                host = f"127.{b}.{c}.{d}"
                url = f"http://{host}:8080"
                # validate: always valid (has host, http scheme)
                t.check(w.validate_url(url)[0], f"valid 127 {host}")
                # loopback-url: ONLY exact 127.0.0.1
                exp_lb = (host == "127.0.0.1")
                t.eq(w.is_loopback_url(url), exp_lb, f"strict loopback {host}")
                # local: entire 127/8 is loopback => local
                t.check(w.is_local_url(url), f"127/8 is local {host}")

    # =====================================================================
    # 3. RFC1918 private ranges -> is_local_url True; is_loopback_url False.
    # =====================================================================
    t.section("RFC1918 private ranges")
    priv_hosts = []
    # 10.0.0.0/8
    for b in [0, 1, 50, 128, 200, 255]:
        for d in [0, 1, 99, 254, 255]:
            priv_hosts.append(f"10.{b}.0.{d}")
    # 192.168.0.0/16
    for c in [0, 1, 2, 100, 200, 255]:
        for d in [0, 1, 50, 254, 255]:
            priv_hosts.append(f"192.168.{c}.{d}")
    # 172.16.0.0/12  (172.16 - 172.31)
    for b in range(16, 32):
        priv_hosts.append(f"172.{b}.0.1")
        priv_hosts.append(f"172.{b}.255.254")
    for host in priv_hosts:
        url = f"http://{host}:8080"
        t.check(w.validate_url(url)[0], f"valid priv {host}")
        t.check(w.is_local_url(url), f"private is local {host}")
        t.check(not w.is_loopback_url(url), f"private not loopback {host}")

    # =====================================================================
    # 4. Boundary: hosts just OUTSIDE the private ranges must be NON-local.
    # =====================================================================
    t.section("just-outside private boundaries (off-by-one)")
    public_boundaries = [
        "9.255.255.255", "11.0.0.0",          # around 10/8
        "192.167.255.255", "192.169.0.0",     # around 192.168/16
        "192.167.0.1", "192.169.1.1",
        "172.15.255.255", "172.32.0.0",       # around 172.16/12
        "172.15.0.1", "172.32.0.1",
        "126.255.255.255", "128.0.0.0",       # around 127/8
        "169.253.255.255", "169.255.0.0",     # around 169.254/16 (link-local)
    ]
    for host in public_boundaries:
        url = f"http://{host}:8080"
        t.check(w.validate_url(url)[0], f"valid boundary {host}")
        t.eq(w.is_local_url(url), exp_local(url), f"boundary local {host}")
        # these are all outside private/loopback -> must be non-local
        t.check(not w.is_local_url(url), f"boundary public not-local {host}")
        t.check(not w.is_loopback_url(url), f"boundary not loopback {host}")

    # =====================================================================
    # 5. 169.254.0.0/16 link-local — ipaddress treats as private -> local.
    # =====================================================================
    t.section("169.254/16 link-local")
    for c in [0, 1, 2, 100, 169, 254, 255]:
        for d in [0, 1, 254, 255]:
            host = f"169.254.{c}.{d}"
            url = f"http://{host}"
            t.check(w.is_local_url(url), f"link-local is local {host}")
            t.check(not w.is_loopback_url(url), f"link-local not loopback {host}")

    # =====================================================================
    # 6. Public hosts / IPs must be NON-local AND NON-loopback.
    # =====================================================================
    t.section("public hosts non-local")
    public_hosts = [
        "8.8.8.8", "1.1.1.1", "208.67.222.222", "93.184.216.34",
        "evil.example.com", "attacker.internal", "google.com", "example.org",
        "169.254.0.0.evil.com", "localhost.evil.com", "127.0.0.1.evil.com",
        "metadata.google.internal", "169-254-169-254.example.com",
        "0x7f000001", "2130706433", "017700000001",
        "registry.npmjs.org", "s3.amazonaws.com", "169.254.169.254.nip.io",
    ]
    for host in public_hosts:
        for scheme in ["http", "https"]:
            url = f"{scheme}://{host}:8080"
            t.check(w.validate_url(url)[0], f"valid public {host}")
            t.eq(w.is_local_url(url), exp_local(url), f"public local-check {host}")
            t.check(not w.is_loopback_url(url), f"public not loopback {host}")
    # decimal/hex/octal IP encodings of 127.0.0.1: NOT parsed as loopback by
    # name -> treated as a hostname -> non-local (documented limitation; we
    # pin the actual behavior so a regression is visible).
    for enc in ["0x7f000001", "2130706433", "017700000001", "127.1", "127.0.1"]:
        url = f"http://{enc}"
        t.eq(w.is_local_url(url), exp_local(url), f"enc local {enc}")
        t.eq(w.is_loopback_url(url), exp_loopback(url), f"enc loopback {enc}")

    # =====================================================================
    # 7. localhost / ::1 variants.
    # =====================================================================
    t.section("localhost and ::1 variants")
    loop_urls = [
        "http://localhost", "https://localhost", "http://localhost:8080",
        "http://localhost:1", "http://localhost:65535", "HTTP://LOCALHOST",
        "http://LocalHost:8080", "http://127.0.0.1", "https://127.0.0.1:443",
        "http://[::1]", "http://[::1]:8080", "https://[::1]:9000",
    ]
    for url in loop_urls:
        t.check(w.validate_url(url)[0], f"valid loop url {url}")
        t.check(w.is_loopback_url(url), f"is loopback {url}")
        t.check(w.is_local_url(url), f"loopback is local {url}")

    # bare ::1 WITHOUT brackets: urlparse can't get a hostname -> invalid,
    # but the lowercased raw host machinery still yields '::1' for the
    # loopback/local checks. Pin the real (documented) behavior.
    for url in ["http://::1", "http://::1:8080"]:
        t.eq(w.validate_url(url)[0], exp_validate(url), f"bare ::1 validate {url}")
        t.eq(w.is_loopback_url(url), exp_loopback(url), f"bare ::1 loopback {url}")
        t.eq(w.is_local_url(url), exp_local(url), f"bare ::1 local {url}")

    # =====================================================================
    # 8. IPv6 sweep — loopback, ULA (fc00::/7), link-local (fe80::/10),
    #    documentation (2001:db8::/32), unspecified (::), global.
    # =====================================================================
    t.section("IPv6 sweep")
    ipv6_hosts = [
        "::1",                       # loopback -> local + (strict) loopback
        "::",                        # unspecified -> private per ipaddress -> local
        "fc00::1", "fcff::1", "fd00::1", "fdff:ffff::1",   # ULA -> private
        "fe80::1", "fe80::abcd", "febf::1",                # link-local -> private
        "2001:db8::1", "2001:db8:dead:beef::1",            # documentation -> private
        "2001:4860:4860::8888",      # google DNS -> global, NON-local
        "2606:4700:4700::1111",      # cloudflare -> global, NON-local
        "::ffff:127.0.0.1",          # v4-mapped loopback -> is_private True
        "::ffff:8.8.8.8",            # v4-mapped public -> non-local
        "64:ff9b::8.8.8.8",          # NAT64 of public -> non-local
    ]
    for host in ipv6_hosts:
        url = f"http://[{host}]:8080"
        t.check(w.validate_url(url)[0], f"valid ipv6 {host}")
        t.eq(w.is_local_url(url), exp_local(url), f"ipv6 local {host}")
        t.eq(w.is_loopback_url(url), exp_loopback(url), f"ipv6 loopback {host}")
    # explicit: a global IPv6 must NOT be local
    for host in ["2001:4860:4860::8888", "2606:4700:4700::1111", "::ffff:8.8.8.8"]:
        t.check(not w.is_local_url(f"http://[{host}]"), f"global ipv6 not local {host}")

    # =====================================================================
    # 9. Port sweep — ports never change validity/local classification.
    # =====================================================================
    t.section("port sweep")
    ports = ["", ":0", ":1", ":80", ":443", ":8080", ":65535", ":65536",
             ":99999", ":abc", ":-1", ":  "]
    for host, is_local, is_loop in [
        ("localhost", True, True), ("127.0.0.1", True, True),
        ("192.168.1.1", True, False), ("8.8.8.8", False, False),
        ("evil.example.com", False, False),
    ]:
        for port in ports:
            url = f"http://{host}{port}"
            # numeric/empty ports keep a parseable host; non-numeric ports make
            # urlparse.hostname raise on access -> the app classifiers crash
            # (no try/except), which is itself a defect we surface via _safe.
            t.eq(_safe(w.is_local_url, url), exp_local(url), f"port local {host}{port}")
            t.eq(_safe(w.is_loopback_url, url), exp_loopback(url), f"port loop {host}{port}")
            t.eq(_safe(lambda u: w.validate_url(u)[0], url), exp_validate(url),
                 f"port valid {host}{port}")

    # =====================================================================
    # 10. Credentials in URL — userinfo must NOT confuse host extraction.
    #     The host after '@' decides locality, not the userinfo before it.
    # =====================================================================
    t.section("credentials-in-url")
    creds = ["user:pass", "user", "admin:secret", "127.0.0.1", "localhost",
             "evil.com", "a:b:c", "user%40name:pw", ""]
    for cred in creds:
        for host, exp_loc in [("127.0.0.1", True), ("localhost", True),
                              ("192.168.0.1", True), ("8.8.8.8", False),
                              ("evil.example.com", False)]:
            pre = (cred + "@") if cred else ""
            url = f"http://{pre}{host}:8080"
            t.eq(w.is_local_url(url), exp_local(url), f"cred local {cred}@{host}")
            t.eq(w.is_loopback_url(url), exp_loopback(url), f"cred loop {cred}@{host}")
            t.check(w.is_local_url(url) == exp_loc, f"cred locality {cred}@{host}")
    # classic SSRF trick: localhost in userinfo, public host after @ -> NON-local
    for url in ["http://localhost@evil.com", "http://127.0.0.1@8.8.8.8",
                "http://localhost:pw@evil.example.com",
                "http://127.0.0.1:8080@attacker.com"]:
        t.check(not w.is_local_url(url), f"userinfo-spoof not local {url}")
        t.check(not w.is_loopback_url(url), f"userinfo-spoof not loopback {url}")

    # =====================================================================
    # 11. Malformed / empty / garbage inputs — must never crash, and must
    #     reject (validate_url False). None/empty are special for is_local.
    # =====================================================================
    t.section("malformed / garbage")
    garbage = [
        "", "   ", "\t", "\n", "notaurl", "://nohost", "http", "http:",
        "http:/", "http://", "http:///", "http:///path", "://", "//host",
        "//localhost:8080", "host:8080", "localhost:8080", "ftp://x",
        "javascript:alert(1)", "data:text/html,x", "file:///etc/passwd",
        "http:// space", "http://ho st/x", "  http://localhost  ",
        "HTTP://", "x" * 500, "http://" + "a" * 300, "http://#frag",
        "http://?q=1", "\x00http://localhost", "http://localhost\x00",
        "http://[", "http://[::", "http://]", "http://[gggg::1]",
        "http://1.2.3", "http://1.2.3.4.5", "http://256.0.0.1",
        "http://...", "http://.", "http://-", "http://_",
    ]
    for url in garbage:
        # never crash + agree with oracle
        v = _safe(w.validate_url, url)
        t.check(isinstance(v, tuple) and len(v) == 2 and v[0] != "CRASH",
                f"validate_url no-crash + tuple {url!r}")
        t.eq(_safe(lambda u: w.validate_url(u)[0], url), exp_validate(url),
             f"garbage validate {url!r}")
        t.eq(_safe(w.is_local_url, url), exp_local(url), f"garbage local {url!r}")
        t.eq(_safe(w.is_loopback_url, url), exp_loopback(url), f"garbage loopback {url!r}")
        # garbage (no http scheme / no host) must be rejected
        if not exp_validate(url) and v[0] != "CRASH":
            t.check(not v[0], f"garbage rejected {url!r}")
            t.check(bool(v[1]), f"rejection has reason {url!r}")

    # ---- explicit SSRF-boundary robustness bug ----------------------------
    # validate_url() correctly try/excepts urlparse, but is_loopback_url() and
    # is_local_url() call urlparse(url).hostname / ipaddress.ip_address(host)
    # WITHOUT a guard, so a malformed bracket/IPv6 host raises ValueError and
    # crashes the classifier. These assertions stay RED until the app guards it.
    t.section("malformed-host must not crash classifiers (BUG)")
    crashers = ["http://[", "http://[::", "http://]", "http://[gggg::1]",
                "http://[12345::]", "https://[::g]", "http://[:::1]"]
    for url in crashers:
        rl = _safe(w.is_loopback_url, url)
        ll = _safe(w.is_local_url, url)
        t.check(not (isinstance(rl, tuple) and rl and rl[0] == "CRASH"),
                f"is_loopback_url must not crash {url!r}")
        t.check(not (isinstance(ll, tuple) and ll and ll[0] == "CRASH"),
                f"is_local_url must not crash {url!r}")

    # None handling: validate False, is_local True (empty host short-circuit),
    # is_loopback False — pin exactly.
    t.eq(w.validate_url(None)[0], False, "validate_url(None) -> False")
    t.eq(w.is_local_url(None), True, "is_local_url(None) -> True (empty-host)")
    t.eq(w.is_loopback_url(None), False, "is_loopback_url(None) -> False")

    # =====================================================================
    # 12. Whitespace handling — validate_url strips; is_loopback/is_local do
    #     NOT strip (urlparse keeps the leading space, scheme fails, host
    #     becomes empty). Pin this divergence so a change is caught.
    # =====================================================================
    t.section("whitespace handling")
    for raw in ["http://localhost:8080", "127.0.0.1:8080"]:
        for pad in ["", " ", "  ", "\t", " \n "]:
            url = f"{pad}http://{raw}{pad}" if not raw.startswith("http") else f"{pad}{raw}{pad}"
            url = f"{pad}http://{raw}{pad}"
            t.eq(w.validate_url(url)[0], exp_validate(url), f"ws validate {url!r}")
            t.eq(w.is_local_url(url), exp_local(url), f"ws local {url!r}")
            t.eq(w.is_loopback_url(url), exp_loopback(url), f"ws loopback {url!r}")
    # validate_url strips, so padded valid url is accepted
    t.check(w.validate_url("  http://localhost:8080  ")[0],
            "padded valid url accepted (validate strips)")

    # =====================================================================
    # 13. Case-insensitivity of host classification.
    # =====================================================================
    t.section("host case-insensitivity")
    for host in ["LOCALHOST", "LocalHost", "localhost", "lOcAlHoSt"]:
        url = f"http://{host}:8080"
        t.check(w.is_loopback_url(url), f"case loopback {host}")
        t.check(w.is_local_url(url), f"case local {host}")

    # =====================================================================
    # 14. Path/query/fragment do not affect host classification.
    # =====================================================================
    t.section("path/query/fragment ignored")
    tails = ["", "/", "/session/status", "/a/b/c", "?x=1", "#f",
             "/p?q=1#f", "/@evil.com", "/x@8.8.8.8"]
    for host, loc, lb in [("127.0.0.1", True, True), ("localhost", True, True),
                          ("10.0.0.1", True, False), ("8.8.8.8", False, False),
                          ("evil.example.com", False, False)]:
        for tail in tails:
            url = f"http://{host}:8080{tail}"
            t.check(w.is_local_url(url) == loc, f"tail local {host}{tail}")
            t.check(w.is_loopback_url(url) == lb, f"tail loop {host}{tail}")
            t.check(w.validate_url(url)[0], f"tail valid {host}{tail}")

    # =====================================================================
    # 15. Broad combinatorial cross-check (oracle agreement) over a large
    #     host x scheme matrix — the bulk of the case count.
    # =====================================================================
    t.section("broad scheme x host matrix")
    matrix_hosts = (
        priv_hosts[:30]
        + ["127.0.0.1", "127.0.0.2", "127.255.255.254", "localhost",
           "8.8.8.8", "1.1.1.1", "evil.example.com", "example.com",
           "192.168.1.1", "10.0.0.1", "172.16.0.1", "169.254.1.1",
           "128.0.0.1", "11.0.0.1", "172.32.0.1"]
    )
    matrix_schemes = ["http", "https", "ftp", "ws", "", "HTTP"]
    matrix_ports = ["", ":8080", ":443", ":1"]
    for host in matrix_hosts:
        for sc in matrix_schemes:
            for port in matrix_ports:
                url = f"{sc}://{host}{port}"
                _ck3(t, w, url, "matrix")
