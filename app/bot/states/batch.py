"""FSM state for batch-upload collection."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BatchFlow(StatesGroup):
    collecting = State()
