"""Reddit research module for BiteAndByte.

Searches health/biohacking subreddits and extracts community consensus
on a given topic using the praw library (Reddit free API).
"""

import logging

import praw

import config

logger = logging.getLogger(__name__)

_reddit: praw.Reddit | None = None


def _get_reddit() -> praw.Reddit:
    """Lazy-initialize read-only Reddit client."""
    global _reddit
    if _reddit is None:
        _reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
    return _reddit


def search_reddit(topic: str, limit: int = 10) -> list[dict]:
    """Search target subreddits for a topic.

    Returns up to *limit* threads (sorted by score), each with their
    top comments extracted.
    """
    reddit = _get_reddit()
    results = []

    for sub_name in config.REDDIT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            for submission in subreddit.search(
                topic, sort="relevance", time_filter="year", limit=limit,
            ):
                submission.comment_sort = "top"
                submission.comments.replace_more(limit=0)

                top_comments = []
                for comment in submission.comments[:5]:
                    if hasattr(comment, "body") and comment.score >= 2:
                        top_comments.append({
                            "body": comment.body[:500],
                            "score": comment.score,
                        })

                results.append({
                    "subreddit": sub_name,
                    "title": submission.title,
                    "score": submission.score,
                    "url": f"https://reddit.com{submission.permalink}",
                    "num_comments": submission.num_comments,
                    "top_comments": top_comments,
                })
        except Exception:
            logger.exception("Failed to search r/%s", sub_name)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def format_reddit_data(threads: list[dict]) -> str:
    """Format Reddit threads into a text block for Gemini prompt injection."""
    if not threads:
        return "לא נמצאו דיונים רלוונטיים ברדיט."

    lines = []
    for i, t in enumerate(threads, 1):
        lines.append(
            f"--- Thread {i} (r/{t['subreddit']}, score: {t['score']}) ---"
        )
        lines.append(f"Title: {t['title']}")
        if t["top_comments"]:
            lines.append("Top comments:")
            for c in t["top_comments"]:
                lines.append(f"  [{c['score']} upvotes]: {c['body']}")
        lines.append("")

    return "\n".join(lines)
