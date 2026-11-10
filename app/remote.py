"""Images fetched from a web address, for the image element.

The server fetches them rather than the browser, which most sites don't let a
page read from (CORS). An address is fetched once, when the user enters it;
the editor stores the image in the template, so nothing is fetched at print
time. With --lan, anyone on the network can ask for a fetch, so:

- only http and https addresses, with a host and no user name or password;
- not this machine or link-local addresses, checked after the name is looked
  up, and again for each redirect (a name whose answer changes between the
  check and the download could still slip through);
- at most MAX_BYTES, within TIMEOUT_S, and no proxy;
- only images come back: PNG, JPEG, WebP or GIF that Pillow can open, or SVG
  whose root is <svg>. Anything else is refused, so a web page or another
  file never reaches the editor.
"""

import base64
import ipaddress
import posixpath
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from io import BytesIO

from PIL import Image

MAX_URL = 2048
MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_S = 10
MAX_REDIRECTS = 5
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}


class FetchError(ValueError):
    """An address that can't be used or fetched, with a message for the user."""


def check_url(url):
    """The address, tidied, if it may be fetched; otherwise FetchError."""
    if not isinstance(url, str) or not url.strip():
        raise FetchError("Enter the image's address")
    url = url.strip()
    if len(url) > MAX_URL:
        raise FetchError(f"That address is longer than {MAX_URL} characters")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise FetchError("That address has spaces or control characters in it")
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port   # raises on a port that isn't a number
    except ValueError:
        raise FetchError("That isn't a web address") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise FetchError("Only http and https addresses can be used")
    if not parts.hostname:
        raise FetchError("That address has no host")
    if parts.username is not None or parts.password is not None:
        raise FetchError("Addresses with a user name or password can't be used")
    try:
        parts.hostname.encode("idna")
    except UnicodeError:
        raise FetchError("That address's host name isn't valid") from None
    return url


def refused(ip):
    """Why an address may not be fetched from, or None. Tests replace this."""
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_unspecified:
        return "that address is this machine"
    if ip.is_link_local:
        return "link-local addresses can't be used"
    if ip.is_multicast:
        return "multicast addresses can't be used"
    return None


def _check_host(url):
    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError(f"Couldn't find {parts.hostname}") from None
    for info in infos:
        why = refused(ipaddress.ip_address(info[4][0].split("%")[0]))   # drop an IPv6 zone
        if why:
            raise FetchError(f"Refused: {why}")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follows a few redirects, each to an address that passes the same checks."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _check_host(check_url(newurl))
        except FetchError:
            fp.close()   # the redirect's own response, which urllib would otherwise leave open
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _image_type(raw):
    """The MIME type of an image Pillow or the browser can use, or None."""
    try:
        with Image.open(BytesIO(raw), formats=list(FORMATS)) as im:
            return FORMATS[im.format]
    except Image.DecompressionBombError:
        raise FetchError("That image has too many pixels") from None
    except Exception:   # Pillow raises several kinds for a file that isn't an image
        pass
    try:
        root = ET.fromstring(raw)   # expat refuses entity bombs and fetches nothing
    except ET.ParseError:
        return None
    return "image/svg+xml" if root.tag in ("svg", "{http://www.w3.org/2000/svg}svg") else None


def _name(url):
    """A short name for the image: the address's file name, or its host."""
    parts = urllib.parse.urlsplit(url)
    name = posixpath.basename(urllib.parse.unquote(parts.path)) or parts.hostname
    return "".join(c for c in name if c.isprintable())[:80] or "image"


def fetch_image(url):
    """{"data": data URL, "name": …, "url": the address} for an image at an address."""
    url = check_url(url)
    _check_host(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects())
    req = urllib.request.Request(url, headers={"User-Agent": "Oh-Brother label printing",
                                               "Accept": "image/*"})
    deadline = time.monotonic() + TIMEOUT_S
    try:
        with opener.open(req, timeout=TIMEOUT_S) as resp:
            length = (resp.headers.get("Content-Length") or "").strip()
            if length.isascii() and length.isdigit() and int(length) > MAX_BYTES:   # a length that isn't a number is ignored
                raise FetchError(f"It's over {MAX_BYTES // 1024 // 1024} MB")
            chunks, size = [], 0
            # read1() gives what has arrived, where read() waits for the full
            # 64 KB: a site sending a byte at a time would otherwise never
            # reach the deadline check below.
            while chunk := resp.read1(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchError(f"It's over {MAX_BYTES // 1024 // 1024} MB")
                if time.monotonic() > deadline:
                    raise TimeoutError
                chunks.append(chunk)
    except urllib.error.HTTPError as e:
        e.close()   # it holds the response open
        raise FetchError(f"Couldn't get it: {e.code} {e.reason}") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, FetchError):   # raised by a redirect's checks
            raise e.reason from None
        if isinstance(e.reason, TimeoutError):
            raise FetchError(f"It took longer than {TIMEOUT_S} seconds") from None
        if isinstance(e.reason, ssl.SSLError):
            raise FetchError("Couldn't get it: the site's security certificate couldn't be checked") from None
        raise FetchError(f"Couldn't get it: {e.reason}") from None
    except TimeoutError:
        raise FetchError(f"It took longer than {TIMEOUT_S} seconds") from None
    except OSError as e:   # the connection dropped partway
        raise FetchError(f"Couldn't get it: {e}") from None
    raw = b"".join(chunks)
    mime = _image_type(raw)
    if not mime:
        raise FetchError("That address isn't an image: use one ending in a PNG, JPEG, WebP, GIF or SVG file")
    return {"data": f"data:{mime};base64," + base64.b64encode(raw).decode(), "name": _name(url), "url": url}
