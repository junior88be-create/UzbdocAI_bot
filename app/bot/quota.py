"""Free-tier request quota gate, shared by the document-conversion and
voice/audio-transcription flows.

A "request" is one user-initiated processing action - picking an output
format for a document (or a whole batch), or sending a voice/audio
message - regardless of whether the underlying extraction turns out to be
a cache hit. There is no in-bot payment flow: once the free quota for the
current period is exhausted, the user is told to arrange payment with an
admin, who then runs /subscribe (see app/bot/handlers/admin.py) to grant
paid access - see app.database.repositories.UserRepository
.check_and_consume_quota for the actual counting/reset logic.
"""

from __future__ import annotations

from datetime import timedelta

from app.config.settings import get_settings
from app.database.database import get_session
from app.database.repositories import UserRepository

_QUOTA_RESET_PERIOD = timedelta(days=30)

_QUOTA_EXCEEDED_MESSAGE = (
    "⛔ Сизнинг ойлик бепул сўровлар лимитингиз ({limit} та) тугади.\n\n"
    "Давом этиш учун ойлик обуна сотиб олишингиз керак - нарх ва тўлов "
    "тартиби юзасидан админ @bekzod_eshniyazov билан боғланинг.\n\n"
    "Лимит ҳар ой автоматик тикланади."
)


async def check_and_consume_quota(db_user_id: str) -> str | None:
    """Returns None if the request is allowed (and consumes one unit of the
    free quota, unless the user is an admin or subscribed) - otherwise
    returns a ready-to-send Uzbek message explaining the block.
    """
    settings = get_settings()
    async with get_session() as session:
        user_repo = UserRepository(session)
        allowed = await user_repo.check_and_consume_quota(
            db_user_id, settings.free_requests_per_month, _QUOTA_RESET_PERIOD
        )
    if allowed:
        return None
    return _QUOTA_EXCEEDED_MESSAGE.format(limit=settings.free_requests_per_month)
