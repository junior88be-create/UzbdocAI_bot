"""FSM state for the full-text search prompt."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SearchFlow(StatesGroup):
    awaiting_query = State()
