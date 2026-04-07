from aiogram.fsm.state import State, StatesGroup


class ReviewStates(StatesGroup):
    waiting_for_target = State()
    waiting_for_type = State()
    waiting_for_comment = State()
    waiting_for_proof = State()


class AppealStates(StatesGroup):
    waiting_for_review_selection = State()
    waiting_for_comment = State()
    waiting_for_proof = State()


class ReferenceStates(StatesGroup):
    waiting_for_target = State()
    waiting_for_ref_username = State()
    waiting_for_proof = State()
