from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


QUERY_VERSION = "Q_V1"
COLLECTOR_VERSION = "COLLECTOR_V2"
CLUSTER_VERSION = "CLUSTER_V3"  # V3: numeric/entity merge guard (Audit #3)
SENTIMENT_VERSION = "GOLD_SENTIMENT_V3"  # V3: Audit #3 F-05/F-07/A3-9 rule fixes


class ProvenanceStatus(str, Enum):
    VERIFIED_SOURCE = "VERIFIED_SOURCE"
    HISTORICAL_UNVERIFIED_AVAILABILITY = "HISTORICAL_UNVERIFIED_AVAILABILITY"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"


LANGUAGE_CODE_MAP: dict[str, str] = {
    "en": "en",
    "english": "en",
    "chinese": "zh",
    "zh": "zh",
    "hindi": "hi",
    "hi": "hi",
    "bengali": "bn",
    "bn": "bn",
    "marathi": "mr",
    "mr": "mr",
    "tamil": "ta",
    "ta": "ta",
    "telugu": "te",
    "te": "te",
    "gujarati": "gu",
    "gu": "gu",
    "malayalam": "ml",
    "ml": "ml",
    "punjabi": "pa",
    "pa": "pa",
    "urdu": "ur",
    "ur": "ur",
    "nepali": "ne",
    "ne": "ne",
    "spanish": "es",
    "es": "es",
    "french": "fr",
    "fr": "fr",
    "german": "de",
    "de": "de",
    "italian": "it",
    "it": "it",
    "portuguese": "pt",
    "pt": "pt",
    "dutch": "nl",
    "nl": "nl",
    "russian": "ru",
    "ru": "ru",
    "ukrainian": "uk",
    "uk": "uk",
    "arabic": "ar",
    "ar": "ar",
    "turkish": "tr",
    "tr": "tr",
    "persian": "fa",
    "fa": "fa",
    "hebrew": "he",
    "he": "he",
    "japanese": "ja",
    "ja": "ja",
    "korean": "ko",
    "ko": "ko",
    "vietnamese": "vi",
    "vi": "vi",
    "indonesian": "id",
    "id": "id",
    "thai": "th",
    "th": "th",
    "greek": "el",
    "el": "el",
    "polish": "pl",
    "pl": "pl",
    "romanian": "ro",
    "ro": "ro",
    "hungarian": "hu",
    "hu": "hu",
    "czech": "cs",
    "cs": "cs",
    "slovak": "sk",
    "sk": "sk",
    "slovenian": "sl",
    "sl": "sl",
    "croatian": "hr",
    "hr": "hr",
    "serbian": "sr",
    "sr": "sr",
    "bosnian": "bs",
    "bs": "bs",
    "bulgarian": "bg",
    "bg": "bg",
    "albanian": "sq",
    "sq": "sq",
    "macedonian": "mk",
    "mk": "mk",
    "swedish": "sv",
    "sv": "sv",
    "norwegian": "no",
    "no": "no",
    "estonian": "et",
    "et": "et",
    "lithuanian": "lt",
    "lt": "lt",
    "azerbaijani": "az",
    "az": "az",
    "kazakh": "kk",
    "kk": "kk",
}

_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and",
    "or", "as", "by", "with", "from", "is", "are", "was", "were",
}

_SEED_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "economictimes.indiatimes.com",
    "cnbc.com",
    "livemint.com",
    "ft.com",
    "wsj.com",
}

# Bare editorial slug ending in -YYYY-MM-DD without a numeric publisher article ID.
_SYNTHETIC_SLUG_RE = re.compile(r"^(?!.*-\d{5,}-\d{4}-\d{2}-\d{2}).*-\d{4}-\d{2}-\d{2}/?$")


def normalize_language(raw_language: str | None) -> str:
    """Normalize free-form GDELT/RSS language labels into lowercase ISO-like codes."""
    if not raw_language or not isinstance(raw_language, str):
        return "unknown"
    cleaned = raw_language.strip().lower()
    if not cleaned:
        return "unknown"
    return LANGUAGE_CODE_MAP.get(cleaned, cleaned[:16])


def compute_canonical_url(url: str) -> str:
    """Normalize URL by removing tracking params while preserving article identity params."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        path = re.sub(r"/+$", "", parsed.path or "")
        filtered_params = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if not k.lower().startswith("utm_")
            and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
        ]
        query = urlencode(sorted(filtered_params))
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return raw


def normalize_headline(title: str) -> str:
    """Normalize headline by stripping trailing publisher attribution and normalizing whitespace."""
    raw = (title or "").strip()
    cleaned = re.sub(r"\s+[-|–—]\s+[A-Za-z0-9\s.&'()/]+$", "", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def extract_story_cluster_key(title: str) -> str:
    """Extract normalized core-event token stem for syndication clustering."""
    no_pub = normalize_headline(title)
    alnum = re.sub(r"[^\w\s]", " ", no_pub)
    tokens = [w for w in alnum.split() if w and w not in _STOPWORDS]
    if len(tokens) >= 6:
        return " ".join(tokens[:6])
    return " ".join(tokens) if tokens else no_pub


def compute_content_fingerprint(title: str, canonical_url: str = "") -> str:
    """Deterministic SHA-256 fingerprint of normalized headline + canonical URL host."""
    norm_title = normalize_headline(title)
    host = ""
    if canonical_url:
        try:
            host = urlparse(canonical_url).netloc.lower()
        except Exception:
            host = ""
    payload = f"{norm_title}|{host}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def extract_template_stem(title: str) -> str:
    """
    Strip volatile numbers, currency figures, and calendar dates/months to detect
    recurring daily price-bulletin or economic-calendar boilerplate templates.
    """
    no_pub = normalize_headline(title)
    stripped = re.sub(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|yesterday)\b",
        " ",
        no_pub,
    )
    stripped = re.sub(r"[$₹€£]?\d[\d.,/:-]*%?", " ", stripped)
    alnum = re.sub(r"[^\w\s]", " ", stripped)
    tokens = [w for w in alnum.split() if w and w not in _STOPWORDS]
    return " ".join(tokens[:8])


def _headline_token_set(title: str) -> set[str]:
    stem = extract_story_cluster_key(title)
    return {t for t in stem.split() if len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Tokens that name a DIFFERENT event even when the rest of the headline is identical
# ("... ahead of US CPI" vs "... ahead of US PPI"). Numbers likewise distinguish daily
# templated bulletins (different prices / dates) and different policy moves (25 vs 50 bps).
_DISTINGUISHING_ENTITY_TOKENS = frozenset({
    "cpi", "ppi", "pce", "gdp", "nfp", "payrolls", "jobs", "jobless", "pmi", "retail", "claims",
    "fed", "fomc", "ecb", "rbi", "boj", "boe", "pboc", "snb",
    "hike", "hikes", "cut", "cuts", "hold", "holds",
    "gold", "silver", "platinum", "oil", "crude", "dollar", "rupee", "yuan", "yen", "euro",
})
_UP_TOKENS = frozenset({"rise", "rises", "gains", "gain", "climbs", "jumps", "surges", "rallies", "higher", "up", "firms"})
_DOWN_TOKENS = frozenset({"fall", "falls", "drops", "slips", "slides", "tumbles", "dips", "lower", "down", "eases", "weakens"})
_NUMERIC_TOKEN_RE = re.compile(r"\d")


def _full_token_set(title: str) -> set[str]:
    no_pub = normalize_headline(title)
    alnum = re.sub(r"[^\w\s]", " ", no_pub)
    return {w for w in alnum.split() if w and w not in _STOPWORDS}


def headline_identity_signature(title: str) -> str:
    """Order-insensitive signature of ALL headline tokens (publisher suffix stripped).
    Used to seed cluster IDs so two different stories that share their first six tokens
    ("... ahead of US CPI data" vs "... US PPI data") can never collide on the same ID."""
    return " ".join(sorted(_full_token_set(title)))


def headlines_conflict(title_a: str, title_b: str) -> bool:
    """True when two similar headlines differ in a number or a distinguishing entity token,
    i.e. they describe different events and must not be merged into one story cluster."""
    a, b = _full_token_set(title_a), _full_token_set(title_b)
    diff = a ^ b
    if any(_NUMERIC_TOKEN_RE.search(t) or t in _DISTINGUISHING_ENTITY_TOKENS for t in diff):
        return True
    # Opposite reported directions ("gold rises ..." vs "gold falls ...") are different stories;
    # synonyms in the same direction ("rises" vs "climbs") are rewordings and may merge.
    a_up, a_dn = bool(a & _UP_TOKENS), bool(a & _DOWN_TOKENS)
    b_up, b_dn = bool(b & _UP_TOKENS), bool(b & _DOWN_TOKENS)
    return (a_up and not a_dn and b_dn and not b_up) or (a_dn and not a_up and b_up and not b_dn)


def headlines_should_merge(title_a: str, title_b: str, jaccard_threshold: float = 0.70) -> tuple[bool, float]:
    """Merge decision used by both in-batch and DB-backed clustering. Returns (merge, jaccard)."""
    score = _jaccard(_headline_token_set(title_a), _headline_token_set(title_b))
    same_key = extract_story_cluster_key(title_a) == extract_story_cluster_key(title_b)
    if not (same_key or score >= jaccard_threshold):
        return False, score
    if headlines_conflict(title_a, title_b):
        return False, score
    return True, (1.0 if same_key else score)


def compute_story_cluster_id(
    title: str,
    event_time: datetime | None,
    cluster_version: str = CLUSTER_VERSION,
) -> tuple[str, str]:
    """
    NEW-4: Deterministic time-bounded single-item cluster ID (`story_cluster_id`, `cluster_key`).
    Includes bounded 14-day UTC epoch window when `event_time` is known so identical headlines
    90 days apart never collapse into one cluster.
    """
    cluster_key = extract_story_cluster_key(title)
    if event_time is not None:
        utc_dt = (
            event_time.replace(tzinfo=timezone.utc)
            if event_time.tzinfo is None
            else event_time.astimezone(timezone.utc)
        )
        epoch_window = int(utc_dt.timestamp() // (2 * 86400))
    else:
        epoch_window = 0
    payload = f"{cluster_version}|w{epoch_window}|{headline_identity_signature(title) or cluster_key}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"clu2_{digest}", cluster_key


def assign_story_clusters(
    items: list[dict],
    *,
    time_field: str = "published_at",
    title_field: str = "title",
    window_hours: float = 36.0,
    jaccard_threshold: float = 0.70,
    cluster_version: str = CLUSTER_VERSION,
) -> list[dict]:
    """
    F-16 / NEW-4 / NEW-5: Cluster syndicated stories chronologically using a fixed-origin
    36-hour time span (no indefinite chaining of daily bulletins) and token-stem Jaccard similarity.
    """
    def _dt_of(row: dict) -> datetime:
        raw = row.get(time_field)
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        parsed = parse_utc_iso(str(raw or ""))
        return parsed or datetime(1970, 1, 1, tzinfo=timezone.utc)

    ordered = sorted(enumerate(items), key=lambda pair: _dt_of(pair[1]))
    max_span_sec = window_hours * 3600.0

    # Each anchor keeps an IMMUTABLE `origin_dt` so daily bulletins cannot chain beyond 36h!
    anchors: list[dict] = []
    assigned: dict[int, tuple[str, str, bool]] = {}

    for orig_idx, row in ordered:
        title = str(row.get(title_field) or "")
        dt = _dt_of(row)
        ckey = extract_story_cluster_key(title)
        tset = _headline_token_set(title)
        tstem = extract_template_stem(title)

        matched_anchor: dict | None = None
        best_score = -1.0
        is_recurring = False
        for anchor in reversed(anchors):
            span_sec = abs((dt - anchor["origin_dt"]).total_seconds())
            if span_sec <= max_span_sec:
                merge, score = headlines_should_merge(title, anchor["title"], jaccard_threshold)
                # Best match wins (ties -> most recent anchor), not merely the first match.
                if merge and score > best_score:
                    matched_anchor = anchor
                    best_score = score
            elif tstem and tstem == anchor["template_stem"]:
                is_recurring = True

        if matched_anchor is not None:
            assigned[orig_idx] = (matched_anchor["cluster_id"], matched_anchor["key"], is_recurring)
        else:
            existing_cids = {a["cluster_id"] for a in anchors}
            origin_day = int(dt.astimezone(timezone.utc).timestamp() // 86400)
            seq = 0
            while True:
                suffix = "" if seq == 0 else f"|{seq}"
                seed = f"{cluster_version}|d{origin_day}|{headline_identity_signature(title) or ckey}{suffix}"
                cid = f"clu2_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
                if cid not in existing_cids:
                    break
                seq += 1
            anchors.append(
                {
                    "cluster_id": cid,
                    "key": ckey,
                    "tokens": tset,
                    "template_stem": tstem,
                    "title": title,
                    "origin_dt": dt,
                }
            )
            assigned[orig_idx] = (cid, ckey, is_recurring)

    enriched: list[dict] = []
    for idx, row in enumerate(items):
        cid, ckey, is_rec = assigned[idx]
        copy_row = dict(row)
        copy_row["story_cluster_id"] = cid
        copy_row["cluster_key"] = ckey
        copy_row["cluster_version"] = cluster_version
        copy_row["is_recurring_template"] = is_rec
        enriched.append(copy_row)
    return enriched


def parse_utc_iso(value: str | None) -> datetime | None:
    """Parse ISO-8601 or space-separated UTC timestamps strictly."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except ValueError:
        return None


def is_synthetic_fixture_url(url: str, source: str = "") -> bool:
    """
    Detect hand-seeded synthetic fixture records whose URLs use fabricated
    domain + editorial -YYYY-MM-DD slugs instead of GDELT / Google News RSS URLs.
    """
    raw_url = (url or "").strip()
    if not raw_url:
        return False
    try:
        host = urlparse(raw_url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
    except Exception:
        host = ""
    src_norm = (source or "").strip().lower()
    if src_norm.startswith("www."):
        src_norm = src_norm[4:]
    in_seed_domain = any(d in host or host == d or d in src_norm for d in _SEED_DOMAINS)
    if not in_seed_domain:
        return False
    return bool(_SYNTHETIC_SLUG_RE.match(raw_url))


def canonicalize_python_source_ast(source: str) -> str:
    """
    Parse Python source into an AST, strip all docstrings and comments, and emit
    a deterministic attribute-free AST dump so documentation/whitespace edits
    never alter implementation fingerprints across Python versions or hash seeds.
    """
    import ast
    import textwrap

    dedented = textwrap.dedent(source)
    tree = ast.parse(dedented)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                getattr(node, "body", None)
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body.pop(0)
    return ast.dump(tree, include_attributes=False)


def compute_cluster_implementation_digest() -> str:
    """
    Deterministic AST-based fingerprint of story clustering semantics in this module,
    excluding comments, docstrings, formatting, and Python bytecode.
    """
    import inspect

    cluster_symbols = (
        normalize_headline,
        extract_story_cluster_key,
        _headline_token_set,
        _jaccard,
        extract_template_stem,
        headline_identity_signature,
        headlines_should_merge,
        compute_story_cluster_id,
        assign_story_clusters,
    )
    parts: list[str] = [
        CLUSTER_VERSION,
        repr(sorted(_STOPWORDS)),
        repr(sorted((k, sorted(v)) for k, v in _EXPLICIT_ENTITY_GROUPS.items()))
        if "_EXPLICIT_ENTITY_GROUPS" in globals()
        else "",
    ]
    for sym in cluster_symbols:
        parts.append(canonicalize_python_source_ast(inspect.getsource(sym)))
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]
