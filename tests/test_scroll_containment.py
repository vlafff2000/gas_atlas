"""Прокручиваемые области не передают прокрутку основному окну (scroll chaining)."""
import re
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parent.parent / "web" / "src"
SCROLL = re.compile(r"overflow(-y)?\s*:\s*(auto|scroll)")
CONTAIN = re.compile(r"overscroll-behavior(-y)?\s*:\s*(contain|none)")
# Область без собственной прокрутки по высоте или внутри окна, где родитель тоже contain
EXEMPT: set[str] = set()


def _rules():
    for css in sorted(CSS_DIR.glob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S)
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            yield css.name, " ".join(m.group(1).split()), m.group(2)


def test_scrollable_areas_contain_overscroll():
    bad = [f"{f}: {sel}" for f, sel, body in _rules()
           if SCROLL.search(body) and not CONTAIN.search(body) and sel not in EXEMPT]
    assert not bad, "нет overscroll-behavior: contain у:\n" + "\n".join(bad)
