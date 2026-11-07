"""Session title contract, normalization, fold and service."""
from .normalize import (
    FALLBACK_MAX_BYTES,
    FALLBACK_MAX_WORDS,
    MAX_TITLE_BYTES,
    clean_title_text,
    fallback_session_title,
    normalize_session_title,
    truncate_title_utf8,
)
from .projection import (
    SOURCE_FALLBACK,
    SOURCE_PROVIDER,
    SOURCE_USER,
    SessionTitle,
    TitleInput,
    TitleMessage,
    collect_title_messages,
    fold_session_title,
    fold_title_input,
    session_title_of,
    title_message_of,
)
from .service import SessionTitleService
from .services import SESSION_TITLE
from .plugin import SessionTitlePlugin

__all__ = [
    "FALLBACK_MAX_BYTES",
    "FALLBACK_MAX_WORDS",
    "MAX_TITLE_BYTES",
    "clean_title_text",
    "fallback_session_title",
    "normalize_session_title",
    "truncate_title_utf8",
    "SOURCE_FALLBACK",
    "SOURCE_PROVIDER",
    "SOURCE_USER",
    "SessionTitle",
    "TitleInput",
    "TitleMessage",
    "collect_title_messages",
    "fold_session_title",
    "fold_title_input",
    "session_title_of",
    "title_message_of",
    "SessionTitleService",
    "SESSION_TITLE",
    "SessionTitlePlugin",
]
