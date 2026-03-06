from .cache_state import FetchCacheState, global_fetch_cache
from .dedupe import canonical_url_fingerprint, content_fingerprint, normalize_canonical_url
from .extract_contract import ExtractedItem, ExtractionResult
from .http_client import FetchResult, create_http_client, fetch_text
from .metrics import new_source_metrics, finalize_source_metrics
from .retry import classify_error_type, should_retry, backoff_with_jitter
from .sitemap import SitemapUrl, collect_sitemap_urls, infer_headline_from_url, parse_sitemap_document

__all__ = [
    "FetchCacheState",
    "global_fetch_cache",
    "canonical_url_fingerprint",
    "content_fingerprint",
    "normalize_canonical_url",
    "ExtractedItem",
    "ExtractionResult",
    "FetchResult",
    "create_http_client",
    "fetch_text",
    "new_source_metrics",
    "finalize_source_metrics",
    "classify_error_type",
    "should_retry",
    "backoff_with_jitter",
    "SitemapUrl",
    "collect_sitemap_urls",
    "parse_sitemap_document",
    "infer_headline_from_url",
]
