"""Versioned, pure action rules used by the shared session action service."""

from dataclasses import dataclass
from types import MappingProxyType

from games.connect4_moves import apply_move as apply_connect4_move
from games.connect4_state import serialize_state as serialize_connect4_state
from games.hangman import HangmanEngine


@dataclass(frozen=True)
class ActionRules:
    apply: object
    public_state: object
    spectator_state: object


ACTION_RULES = MappingProxyType({
    ("connect4", "0.1"): ActionRules(
        apply=apply_connect4_move,
        public_state=serialize_connect4_state,
        spectator_state=serialize_connect4_state,
    ),
    ("hangman", "0.1"): ActionRules(
        apply=HangmanEngine().apply_action,
        public_state=HangmanEngine().get_public_state,
        spectator_state=HangmanEngine().get_spectator_state,
    ),
})
