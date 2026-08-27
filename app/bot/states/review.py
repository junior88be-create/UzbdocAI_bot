"""FSM state for the OCR review step."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ReviewFlow(StatesGroup):
    reviewing = State()
    awaiting_correction = State()
