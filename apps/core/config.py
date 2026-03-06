from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # core
    ENV: str = "dev"
    APP_NAME: str = "market-intel"
    API_KEY: str = "change-me"
    INTERNAL_API_KEY: str = "internal-change-me"
    OPERATOR_USERNAME: str = "operator"
    OPERATOR_PASSWORD: str = "change-me"
    SESSION_AUTH_ENABLED: bool = True
    SESSION_SECRET: str = "change-session-secret"
    SESSION_COOKIE_NAME: str = "mip_session"
    SESSION_TTL_SECONDS: int = 43200
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"

    # db
    DATABASE_URL: str = "postgresql+asyncpg://marketintel:marketintel@postgres:5432/market_intel"

    # redis
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_STREAM_COMMANDS: str = "commands.run.v1"
    REDIS_STREAM_RUN_EVENTS: str = "runs.events.v1"
    REDIS_STREAM_ANALYST_REPORTS: str = "analyst.report.generated.v1"
    REDIS_STREAM_ARCHIVIST_PATTERNS: str = "archivist.patterns.updated.v1"
    REDIS_STREAM_SYSTEM_EVENTS: str = "system.events.v1"
    REDIS_STREAM_MAXLEN: int = 10000
    RUNTIME_OVERRIDES_REDIS_KEY: str = "ops:runtime_overrides:v1"
    RUNTIME_OVERRIDES_CACHE_TTL_SECONDS: int = 10
    SELF_MOD_AUTO_APPLY_ENABLED: bool = True
    SELF_MOD_BACKGROUND_ENABLED: bool = True
    SELF_MOD_RECOMPUTE_INTERVAL_SECONDS: int = 900
    SCHEDULES_CONFIG_PATH: str = "config/schedules.yml"
    AGENT_DEPENDENCIES_CONFIG_PATH: str = "config/agent_dependencies.yml"
    RUN_DB_WRITE_ENABLED: bool = False
    STALE_RUN_RECONCILER_ENABLED: bool = True
    STALE_RUN_RECONCILER_INTERVAL_SECONDS: int = 60
    ANNOUNCEMENTS_STALE_RUN_TTL_MINUTES: int = 20
    BRIEFING_STALE_RUN_TTL_MINUTES: int = 30
    SENTIMENT_STALE_RUN_TTL_MINUTES: int = 45
    ANALYST_STALE_RUN_TTL_MINUTES: int = 30
    ARCHIVIST_STALE_RUN_TTL_MINUTES: int = 45
    NARRATOR_STALE_RUN_TTL_MINUTES: int = 30
    LLM_MODE: str = "off"
    LLM_API_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "meta/llama-3.3-70b-instruct"
    LLM_PROVIDER: str = "openai-compatible"
    LLM_HEALTHCHECK_NETWORK: bool = False
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = ""
    X_API_BEARER_TOKEN: str = ""
    X_NITTER_BASE_URL: str = "https://nitter.net"
    YOUTUBE_API_KEY: str = ""
    ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD: float = 0.70
    ANNOUNCEMENT_LLM_MAX_CALLS_PER_RUN: int = 25
    ANNOUNCEMENT_LLM_MAX_CONCURRENCY: int = 5
    ANNOUNCEMENT_LLM_BREAKER_FAIL_THRESHOLD: int = 3
    ANNOUNCEMENT_LLM_TIMEOUT_SECONDS: int = 8
    ANNOUNCEMENTS_ALPHA_ENRICH_ENABLED: bool = True
    ANNOUNCEMENTS_ALPHA_MAX_TICKERS_PER_RUN: int = 4
    ANNOUNCEMENT_INSIGHT_ENABLED: bool = True
    ANNOUNCEMENT_INSIGHT_CACHE_TTL_MINUTES: int = 360
    ANNOUNCEMENT_INSIGHT_MAX_TOKENS: int = 350
    ANNOUNCEMENT_INSIGHT_TIMEOUT_SECONDS: int = 10
    ANNOUNCEMENT_CONTEXT_MIN_DETAILS_CHARS: int = 240
    ANNOUNCEMENT_CONTEXT_STALE_HOURS: int = 24
    NARRATOR_ENABLED: bool = True
    NARRATOR_CACHE_TTL_MINUTES: int = 360
    NARRATOR_TIMEOUT_SECONDS: int = 20
    NARRATOR_MAX_TOKENS: int = 500
    NARRATOR_CONTEXT_MAX_SOURCES: int = 5
    NARRATOR_MIN_COVERAGE_SCORE: float = 0.6
    NARRATOR_LLM_RETRY_ATTEMPTS: int = 3
    NARRATOR_LLM_BACKOFF_BASE_SECONDS: float = 1.0
    NARRATOR_LLM_CONNECT_TIMEOUT_SECONDS: int = 10
    NARRATOR_LLM_READ_TIMEOUT_SECONDS: int = 90
    NARRATOR_MARKET_STORY_MAX_AGE_MINUTES: int = 60
    NARRATOR_DEGRADED_RETRY_MINUTES: int = 10

    # email
    EMAIL_FROM: str = "briefing@yourdomain.com"
    EMAIL_RECIPIENTS: str = ""  # comma-separated
    EMAIL_PROVIDER: str = "auto"  # auto|sendgrid|smtp|none
    SENDGRID_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    EMAIL_DRY_RUN: bool = False
    EMAIL_EXEC_DIGEST_ENABLED: bool = True
    EMAIL_EXEC_DIGEST_PARALLEL_LEGACY: bool = True
    EMAIL_EXEC_DIGEST_PARALLEL_DAYS: int = 7
    EMAIL_ALERTS_HIGH_IMPACT_ONLY: bool = True
    EMAIL_ALERTS_KENYA_IMPACT_THRESHOLD: int = 60
    EMAIL_EXEC_DIGEST_USE_AGENT_F: bool = True
    EMAIL_EXEC_DIGEST_MAX_STORIES: int = 12
    EMAIL_EXEC_DIGEST_INCLUDE_GLOSSARY: bool = True
    EMAIL_VALIDATION_ENABLED: bool = True
    EMAIL_VALIDATION_RECIPIENTS: str = ""
    EMAIL_VALIDATION_DAILY_HOUR_EAT: int = 10
    EMAIL_VALIDATION_WEEKLY_HOUR_EAT: int = 9
    EMAIL_VALIDATION_WAIT_TIMEOUT_SECONDS: int = 180
    EMAIL_VALIDATION_POLL_INTERVAL_SECONDS: int = 2

    # scraping
    REQUEST_TIMEOUT: int = 30
    PER_DOMAIN_MIN_DELAY_SECONDS: int = 2
    ENABLED_ANNOUNCEMENT_SOURCES: str = ""
    ENABLE_GLOBAL_OUTSIDE_SOURCES: bool = True
    GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD: int = 60
    ENABLE_PREMIUM_GLOBAL_SOURCES: bool = False
    ENABLE_SITEMAP_SOURCES: bool = True
    ENABLE_GLOBAL_MARKETS_THEME_PACK: bool = True
    ENABLE_GLOBAL_EXTRAS_PACK: bool = True
    SITEMAP_MAX_URLS_PER_SOURCE: int = 200
    SITEMAP_LOOKBACK_HOURS: int = 72
    SOURCE_HEALTH_FAIL_OPEN: bool = False
    ANNOUNCEMENTS_LOOKBACK_DAYS: int = 30
    ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE: int = 500
    ANNOUNCEMENTS_ALERT_CANDIDATE_LIMIT: int = 40
    ANNOUNCEMENTS_DETAILS_ENRICH_LIMIT: int = 8
    ANNOUNCEMENTS_DETAILS_ENRICH_TIMEOUT_SECONDS: int = 8
    ANNOUNCEMENTS_COMPANY_IR_MAX_COMPANIES_PER_RUN: int = 10
    ANNOUNCEMENTS_COMPANY_IR_CONCURRENCY: int = 4
    ANNOUNCEMENTS_SOURCE_COLLECTION_MAX_SECONDS: int = 45
    SOURCE_BREAKER_ENABLED: bool = True
    SOURCE_FAIL_THRESHOLD: int = 5
    SOURCE_COOLDOWN_MINUTES: int = 60
    ANNOUNCEMENTS_CONFIG_PATH: str = "config/sources.yml"
    UNIVERSE_CONFIG_PATH: str = "config/universe.yml"
    COMPANY_IR_CONFIG_PATH: str = "config/company_ir.yml"
    ANNOUNCEMENT_TYPES_CONFIG_PATH: str = "config/announcement_types.yml"
    USER_AGENT: str = "MarketIntelBot/1.0 (+https://localhost; contact: admin@example.com)"
    ALPHA_VANTAGE_API_KEY: str = ""

    # stage 3 (daily briefing)
    DAILY_BRIEFING_ENABLED: bool = True
    DAILY_BRIEFING_RUN_HOUR_EAT: int = 8
    DAILY_BRIEFING_FORCE_SEND: bool = False
    DAILY_BRIEFING_LOOKBACK_DAYS: int = 7
    ENABLED_PRICE_SOURCES: str = "mystocks"
    ENABLED_INDEX_SOURCES: str = "nse_market_stats,mystocks"
    ENABLED_FX_SOURCES: str = "erapi"
    ENABLED_NEWS_SOURCES: str = (
        "standard_rss,google_news_ke,bbc_business_rss,mystocks_news,"
        "theonlinekenyan_feed,kenyans_sitemap_news,pulse_ke_sitemap_news,infoworld_feed,"
        "eia_today_in_energy,world_bank_commodity_markets,fred_dollar_index_broad,"
        "google_research_blog,google_deepmind_blog,anthropic_news,durovscode_site,investing_major_indices,"
        "global_bonds_yields_rss,global_earnings_dividends_rss,global_equities_trading_rss"
    )
    BRIEFING_SOURCES_CONFIG_PATH: str = "config/briefing_sources.yml"
    BRIEFING_MIN_PRICE_COVERAGE_PCT: float = 0.6
    AGENT_A_MIN_PRICE_COVERAGE_PCT: float = 0.6
    AGENT_A_PRICE_MAX_CONCURRENCY: int = 4
    AGENT_A_FX_STALE_TTL_HOURS: int = 24
    AGENT_A_FX_HARD_STALE_TTL_HOURS: int = 72
    AGENT_A_INDEX_MIN_VALUE: float = 100.0
    AGENT_A_INDEX_MAX_VALUE: float = 20000.0
    AGENT_A_INDEX_MAX_PCT_MOVE: float = 25.0
    AGENT_A_NEWS_MAX_ITEMS_PER_SOURCE: int = 25
    AGENT_A_ENABLE_NEWS_HTML_SOURCES: bool = False
    AGENT_A_BRIEF_LLM_TIMEOUT_SECONDS: int = 12
    AGENT_A_BRIEF_LLM_MAX_TOKENS: int = 300
    AGENT_A_CHART_OUTPUT_DIR: str = "docs/evidence/agent_a/charts"
    AGENT_A_CHART_ENABLE_VOLUME_OVERLAY: bool = True

    # stage 4 (weekly sentiment)
    SENTIMENT_ENABLED: bool = True
    SENTIMENT_WEEKLY_HOUR_EAT: int = 7
    SENTIMENT_FORCE_RESEND: bool = False
    SENTIMENT_WINDOW_DAYS: int = 7
    ENABLED_SENTIMENT_SOURCES: str = (
        "reddit_rss,x_search_api,youtube_api,"
        "mystocks_forum,stockswatch_forum,business_daily_comments,standardmedia_comments,"
        "google_news_ke_markets,google_news_ke_companies,"
        "google_news_ke_banking,google_news_ke_dividends,"
        "bbc_business_rss,standard_business_rss,"
        "eia_oil_theme_rss,global_oil_theme_rss,global_usd_theme_rss,global_ai_theme_rss,"
        "global_bonds_theme_rss,global_earnings_dividends_theme_rss,global_equities_trading_theme_rss,"
        "theonlinekenyan_feed,kenyans_sitemap_news,pulse_ke_sitemap_news,infoworld_feed,"
        "google_research_blog,google_deepmind_blog,anthropic_news,"
        "durovscode_site,investing_major_indices"
    )
    SENTIMENT_CONFIDENCE_THRESHOLD: float = 0.70
    SENTIMENT_THRESHOLD_BULL: float = 0.20
    SENTIMENT_THRESHOLD_BEAR: float = -0.20
    SENTIMENT_MIN_MENTIONS_PER_TICKER: int = 3
    SENTIMENT_LLM_MAX_CALLS_PER_RUN: int = 25
    SENTIMENT_LLM_BREAKER_FAIL_THRESHOLD: int = 5
    SENTIMENT_CONFIG_PATH: str = "config/sentiment_sources.yml"
    SENTIMENT_ALPHA_ENRICH_ENABLED: bool = True
    SENTIMENT_ALPHA_MAX_TICKERS_PER_RUN: int = 6
    SENTIMENT_ALPHA_MIN_MENTIONS: int = 5

    # stage 5 (analyst synthesis)
    ANALYST_ENABLED: bool = True
    ANALYST_DAILY_HOUR_EAT: int = 9
    ANALYST_WEEKLY_HOUR_EAT: int = 8
    ANALYST_FORCE_RESEND: bool = False
    ANALYST_LOOKBACK_DAYS: int = 7
    ANALYST_MAX_EVENTS: int = 30
    ANALYST_MIN_CONFIDENCE_FOR_STRONG_LANGUAGE: float = 0.70
    ANALYST_REPORT_TYPES: str = "daily,weekly"
    ANALYST_USE_INTERNAL_APIS: bool = True
    ANALYST_USE_ARCHIVIST_FEEDBACK: bool = True
    ANALYST_PATTERN_FEEDBACK_MIN_ACTIVE_PATTERNS: int = 3
    ANALYST_PATTERN_FEEDBACK_WEIGHT_CAP: float = 0.60

    # stage 6 (archivist)
    ARCHIVIST_PROMOTION_THRESHOLD_PCT: float = 65.0
    ARCHIVIST_RETIRE_THRESHOLD_PCT: float = 45.0
    ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM: int = 5
    ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE: int = 8
    ARCHIVIST_REGIME_ADJUSTMENTS_ENABLED: bool = True
    ARCHIVIST_REGIME_RISK_ON_PROMOTION_DELTA_PCT: float = -3.0
    ARCHIVIST_REGIME_RISK_ON_RETIRE_DELTA_PCT: float = -2.0
    ARCHIVIST_REGIME_RISK_OFF_PROMOTION_DELTA_PCT: float = 5.0
    ARCHIVIST_REGIME_RISK_OFF_RETIRE_DELTA_PCT: float = 3.0
    ARCHIVIST_REPLACEMENT_RETIRE_DOMINANCE_DAYS: int = 7
    ARCHIVIST_REPLACEMENT_RETIRE_DOMINANCE_RATIO: float = 1.5
    ARCHIVIST_REPLACEMENT_MIN_ACTIVE_CONFIRMED: int = 3
    ARCHIVIST_REPLACEMENT_UPSTREAM_QUALITY_FLOOR: float = 55.0
    ARCHIVIST_MONTHLY_LOOKBACK_WEEKS: int = 12
    ARCHIVIST_WEEKLY_LOOKBACK_DAYS: int = 30
    ARCHIVIST_ENABLE_EMAIL_REPORTS: bool = True
    ARCHIVIST_FORCE_RESEND: bool = False
    ARCHIVIST_USE_API_FALLBACK: bool = True
    ARCHIVIST_UPSTREAM_QUALITY_MIN_SCORE: float = 70.0
    ARCHIVIST_INPUT_MODE: str = "analyst_only"  # analyst_only|hybrid

    # local llm (optional)
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "mistral:7b"

    # microservices (internal routing)
    GATEWAY_SERVICE_URL: str = "http://gateway-service:8000"
    GATEWAY_PROXY_TIMEOUT_SECONDS: int = 90
    AGENT_A_SERVICE_URL: str = "http://agent-a-service:8001"
    AGENT_B_SERVICE_URL: str = "http://agent-b-service:8002"
    AGENT_C_SERVICE_URL: str = "http://agent-c-service:8003"
    AGENT_D_SERVICE_URL: str = "http://agent-d-service:8004"
    AGENT_E_SERVICE_URL: str = "http://agent-e-service:8005"
    AGENT_F_SERVICE_URL: str = "http://agent-f-service:8006"
    RUN_LEDGER_SERVICE_URL: str = "http://run-ledger-service:8011"


@lru_cache
def get_settings() -> Settings:
    return Settings()
