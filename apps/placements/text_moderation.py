import re
import unicodedata
from pathlib import Path

from django.core.exceptions import ValidationError


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")


BLOCKED_WORDS = frozenset(
    normalize(word)
    for word in Path(__file__).with_name("blocked_words.txt").read_text(encoding="utf-8").split()
)
WORD = re.compile(r"[^\W_]+")


def validate_public_text(text):
    normalized_text = unicodedata.normalize("NFKC", text)
    for match in WORD.finditer(normalized_text):
        word = match.group()
        if normalize(word) in BLOCKED_WORDS:
            raise ValidationError(
                'Слово "%(word)s" запрещено уберите его и отправьте снова.',
                code="blocked_word",
                params={"word": word},
            )
