from .html_discussion import collect as collect_html_discussion
from .reddit_praw import collect as collect_reddit_praw
from .reddit_rss import collect as collect_reddit_rss
from .rss_news import collect as collect_rss_news
from .sitemap_news import collect as collect_sitemap_news
from .x_api import collect as collect_x_api
from .x_dual import collect as collect_x_dual
from .youtube_api import collect as collect_youtube_api

PARSER_REGISTRY = {
    "html_discussion.collect": collect_html_discussion,
    "reddit_praw.collect": collect_reddit_praw,
    "reddit_rss.collect": collect_reddit_rss,
    "rss_news.collect": collect_rss_news,
    "sitemap_news.collect": collect_sitemap_news,
    "x_api.collect": collect_x_api,
    "x_dual.collect": collect_x_dual,
    "youtube_api.collect": collect_youtube_api,
}
