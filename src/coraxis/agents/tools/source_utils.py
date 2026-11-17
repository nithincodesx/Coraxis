"""Source quality and URL normalization utilities.

All classification here is *heuristic*: it is based on URL shape and domain
name only, never on fetched content or third-party reputation services. It is
therefore explicitly labelled as heuristic throughout and must never be
presented as factual verification of authority or truthfulness.

Nothing in this module performs network access.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

#: Query parameters that are purely tracking / session instrumentation and do
#: not change the logical document requested. Removing them lets us treat
#: otherwise-distinct URLs as duplicates without losing meaningful content.
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "igsc",
    "gclid",
    "dclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "medium",
}


def normalize_url(url: str) -> str:
    """Return a normalized, dedup-friendly form of ``url``.

    Normalization:
    * lower-cases scheme and host,
    * removes default ports (``http:80``, ``https:443``),
    * strips the fragment,
    * drops well-known tracking query parameters,
    * sorts the remaining query parameters (order rarely changes a document).

    The original URL is preserved by callers for display; this function is used
    only for duplicate detection. Parameters that materially change content are
    intentionally kept.
    """
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    host = parsed.hostname or ""
    host = host.lower()
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host if port is None else f"{host}:{port}"

    path = parsed.path
    if len(path) > 1:
        path = path.rstrip("/")

    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query.sort()

    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))


def same_document(url_a: str, url_b: str) -> bool:
    """True when two URLs point at the same logical document."""
    return normalize_url(url_a) == normalize_url(url_b)


#: Hostname suffixes that strongly indicate a primary / official source for
#: their respective topic areas. Used only as a heuristic signal; never as
#: proof of authority. Stored without a leading dot.
_PRIMARY_HOST_SUFFIXES = (
    "gov",
    "gc.ca",
    "gov.uk",
    "gov.au",
    "gov.nz",
    "europa.eu",
    "ec.europa.eu",
    "parliament.uk",
    "congress.gov",
    "whitehouse.gov",
    "nih.gov",
    "cdc.gov",
    "fda.gov",
    "uspto.gov",
    "w3.org",
    "ietf.org",
    "rfc-editor.org",
    "iso.org",
)

#: Domains strongly associated with academic / scholarly publishing.
_ACADEMIC_HOST_SUFFIXES = (
    "edu",
    "ac.uk",
    "ac.nz",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "scholar.google",
    "jstor.org",
)

#: Domains associated with established journalism / news.
_NEWS_HOST_SUFFIXES = (
    "nytimes.com",
    "washingtonpost.com",
    "wsj.com",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "economist.com",
    "npr.org",
    "bloomberg.com",
    "ft.com",
)

#: Generic documentation-hosting platforms (not primary sources themselves,
#: but commonly used for official project documentation).
_DOC_HOST_SUFFIXES = (
    "readthedocs.io",
    "github.io",
    "gitbook.io",
    "notion.site",
)


def _host_matches(host: str, suffix: str) -> bool:
    """True when ``host`` equals ``suffix`` or is a subdomain of it."""
    return host == suffix or host.endswith("." + suffix)


def classify_source(url: str) -> str:
    """Heuristically classify one URL into a source category.

    Returns one of: ``primary``, ``official_documentation``, ``academic``,
    ``news``, ``reference``, ``general``. Classification is based solely on
    URL shape and domain name, so it is intentionally labelled heuristic and
    must not be presented as verified authority.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    #: Exact host match takes priority for known primary / official hosts.
    for suffix in _PRIMARY_HOST_SUFFIXES:
        if _host_matches(host, suffix):
            return "primary"

    for suffix in _ACADEMIC_HOST_SUFFIXES:
        if _host_matches(host, suffix):
            return "academic"

    for suffix in _NEWS_HOST_SUFFIXES:
        if _host_matches(host, suffix):
            return "news"

    #: Documentation-like paths or hosts.
    if any(seg in path for seg in ("/docs/", "/documentation/", "/api/", "/reference/")):
        return "official_documentation"
    for suffix in _DOC_HOST_SUFFIXES:
        if _host_matches(host, suffix):
            return "official_documentation"

    return "general"


def domain_of(url: str) -> str:
    """Return the lower-cased host of ``url``, or ``''`` if unparseable."""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
