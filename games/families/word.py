"""Word reveal patterns independent of a particular word game."""

from __future__ import annotations

from collections.abc import Iterable
import string


def mask_answer(answer: str, guessed_letters: Iterable[str], *, hidden: str = "_") -> str:
    """Reveal guessed uppercase letters and preserve separators."""

    if not isinstance(answer, str) or not answer or any(
        letter not in string.ascii_uppercase + " -'" for letter in answer
    ):
        raise ValueError("answer must contain uppercase letters and supported separators")
    if not isinstance(hidden, str) or len(hidden) != 1:
        raise ValueError("hidden marker must be one character")
    guessed = tuple(guessed_letters)
    if any(type(letter) is not str or len(letter) != 1 or letter not in string.ascii_uppercase for letter in guessed):
        raise ValueError("guesses must be single uppercase letters")
    known = set(guessed)
    return "".join(letter if letter in known or letter not in string.ascii_uppercase else hidden for letter in answer)
