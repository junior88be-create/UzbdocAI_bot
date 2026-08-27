"""FSM states used by the bot."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class DocumentFlow(StatesGroup):
    awaiting_file = State()
    processing = State()
