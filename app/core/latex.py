"""LaTeX math → readable Unicode (INF ai, stdlib only, pure).

Problem: students get replies with TeX like
``\\[ 6CO_2 + 6H_2O \\xrightarrow{...} C_6H_{12}O_6 + 6O_2 \\]`` and
Flet's Markdown widget cannot render LaTeX — they see raw source.
This converts common school-level TeX (display/inline math, arrows,
\\frac, sub/superscripts, Greek, \\cdot/\\times) plus bare ``H_2O``-style
subscripts into plain Unicode (``6CO₂ + 6H₂O → (…) C₆H₁₂O₆ + 6O₂``).

Rules:
- Fenced code blocks (``` / ~~~) are NEVER touched — TeX source shown
  intentionally as code stays verbatim.
- History/DB keeps the raw text; conversion is render-only.
- Unknown commands pass through untouched (no data loss).
- Idempotent: running twice changes nothing.
"""

from __future__ import annotations

import re

_SUB = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "i": "ᵢ", "o": "ₒ", "u": "ᵤ",
    "n": "ₙ", "x": "ₓ", "h": "ₕ", "k": "ₖ", "l": "ₗ",
    "m": "ₘ", "p": "ₚ", "s": "ₛ", "t": "ₜ", "r": "ᵣ", "c": "꜀",
}
_SUP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ",
    "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "j": "ʲ", "k": "ᵏ",
    "l": "ˡ", "m": "ᵐ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ",
    "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
}

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
    "lambda": "λ", "mu": "μ", "pi": "π", "sigma": "σ",
    "phi": "φ", "omega": "ω", "Delta": "Δ", "Gamma": "Γ",
    "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Sigma": "Σ",
    "Phi": "Φ", "Omega": "Ω",
}

_SYMBOLS = {
    "cdot": "·", "times": "×", "div": "÷", "pm": "±",
    "approx": "≈", "neq": "≠", "leq": "≤", "geq": "≥",
    "infty": "∞", "degree": "°", "rightarrow": "→", "to": "→",
    "leftarrow": "←", "Rightarrow": "⇒", "leftrightarrow": "↔",
}

# \wrapper{...} commands whose content is plain text already.
_TEXT_WRAPPERS = ("text", "mathrm", "mathbf", "mathit", "mathsf", "ce")


def _sub_map(s: str) -> str:
    return "".join(_SUB.get(ch, ch) for ch in s)


def _sup_map(s: str) -> str:
    return "".join(_SUP.get(ch, ch) for ch in s)


def _brace_arg(s: str, i: int) -> tuple[str, int] | None:
    """Parse s[i] == '{' → (inner content, index after closing brace)."""
    if i >= len(s) or s[i] != "{":
        return None
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1: j], j + 1
    return None


def _replace_cmd_args(s: str, cmd: str, repl) -> str:
    """Replace \\cmd{...} (brace-aware, repeatable) using repl(inner)."""
    while True:
        m = re.search(r"\\" + cmd + r"\{", s)
        if not m:
            return s
        parsed = _brace_arg(s, m.end() - 1)
        if parsed is None:
            return s
        inner, after = parsed
        s = s[: m.start()] + repl(inner) + s[after:]


def _convert_math(inner: str, _depth: int = 0) -> str:
    """Convert the inside of one math span to Unicode."""
    if _depth > 6:
        # Adversarial nesting (\frac{\frac{...}}) — bail out instead of RecursionError.
        return inner[:2000]
    if not isinstance(inner, str):
        return ""
    # Cap span size: MB replies with DOTALL spans stall the UI.
    if len(inner) > 20000:
        inner = inner[:20000]
    s = inner
    # \begin{env} / \end{env} wrappers add nothing on a phone screen.
    s = re.sub(r"\\begin\{[a-zA-Z*]+\}", "", s)
    s = re.sub(r"\\end\{[a-zA-Z*]+\}", "", s)
    # \xrightarrow{label} / \xleftarrow{label} -> arrow (label).
    s = re.sub(r"\\xrightarrow\{([^{}]*)\}", r"→ (\1)", s)
    s = re.sub(r"\\xleftarrow\{([^{}]*)\}", r"← (\1)", s)
    # \frac{a}{b} -> a/b and \sqrt[n]{x} -> √(x) (brace-aware so school
    # formulas with nested {…} don't mangle; args convert recursively).
    while True:
        m = re.search(r"\\[dt]?frac\{", s)
        if not m:
            break
        first = _brace_arg(s, m.end() - 1)
        if first is None:
            break
        num, k = first
        second = _brace_arg(s, k) if k < len(s) else None
        if second is None:
            break
        den, k2 = second
        s = s[: m.start()] + f"{_convert_math(num, _depth + 1)}/{_convert_math(den, _depth + 1)}" + s[k2:]
        if len(s) > 30000:  # pathological input — stop expanding
            break
    s = _replace_cmd_args(s, r"sqrt", lambda b: "√(" + _convert_math(b, _depth + 1) + ")")
    # \text{...} etc. -> bare content.
    for w in _TEXT_WRAPPERS:
        s = re.sub(r"\\" + w + r"\{([^{}]*)\}", r"\1", s)
    # Named symbols + Greek.
    for name, uni in {**_SYMBOLS, **_GREEK}.items():
        s = s.replace("\\" + name, uni)
    # Escaped literals.
    for esc, uni in (("_", "_"), ("%", "%"), ("&", "&"), ("$", "$"),
                     ("{", "{"), ("}", "}"), (" ", " ")):
        s = s.replace("\\" + esc, uni)
    # Line breaks inside math -> separator.
    s = s.replace("\\\\", " ; ")
    # Subscripts: X_{12} / X_2 (digits + common letters only).
    s = re.sub(r"_\{([0-9+\-=()a-zA-Z]+)\}", lambda m: _sub_map(m.group(1)), s)
    s = re.sub(r"_([0-9])", lambda m: _sub_map(m.group(1)), s)
    # Superscripts: X^{2-} / X^2.
    s = re.sub(r"\^\{([0-9+\-=()a-zA-Z]+)\}", lambda m: _sup_map(m.group(1)), s)
    s = re.sub(r"\^([0-9n])", lambda m: _sup_map(m.group(1)), s)
    # Leftover grouping braces are display noise.
    s = s.replace("{", "").replace("}", "")
    # Tidy whitespace (keep single spaces inside formulas).
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


# Span patterns tried in order: display math first (longest delimiters).
_SPAN_RES = (
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),      # \[ ... \]
    re.compile(r"\$\$(.+?)\$\$", re.DOTALL),      # $$ ... $$
    re.compile(r"\\\((.+?)\\\)", re.DOTALL),      # \( ... \)
)

_INLINE_DOLLAR_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)

# Bare H_2O / x^2 outside math spans (digit-only, so _emphasis_ is safe).
# Lookbehind also accepts produced sub/superscripts so SO_4^{2-} chains.
# NOTE: keep the ASCII ranges intact — only the generated Unicode suffix is
# escaped. Escaping the whole class would turn the `A-Z` range into literals
# (A, -, Z) and break plain-English matches like H_2O.
_SCRIPT_UNICODE_CLASS = "".join(
    re.escape(c) for c in sorted(set(_SUB.values()) | set(_SUP.values()))
)
_SCRIPT_PREV = "A-Za-z0-9\\)\\]" + _SCRIPT_UNICODE_CLASS
_BARE_SUB_RE = re.compile(
    r"(?<=[%s])_\{([0-9+\-=()]+)\}|(?<=[%s])_([0-9])" % (_SCRIPT_PREV, _SCRIPT_PREV))
_BARE_SUP_RE = re.compile(
    r"(?<=[%s])\^\{([0-9+\-=()]+)\}|(?<=[%s])\^([0-9n])" % (_SCRIPT_PREV, _SCRIPT_PREV))

_FENCE_RE = re.compile(r"(```.*?```|~~~.*?~~~)", re.DOTALL)


def _convert_segment(seg: str) -> str:
    """Convert one non-code segment (may hold math spans + bare scripts)."""
    out: list[str] = []
    pos = 0
    # Collect math spans from all span patterns.
    spans: list[tuple[int, int, str, bool]] = []  # (start, end, inner, block)
    for rx, block in (( _SPAN_RES[0], True), (_SPAN_RES[1], True), (_SPAN_RES[2], False)):
        for m in rx.finditer(seg):
            spans.append((m.start(), m.end(), m.group(1), block))
    spans.sort()
    # Drop overlaps (earlier/longer match wins).
    kept: list[tuple[int, int, str, bool]] = []
    for sp in spans:
        if kept and sp[0] < kept[-1][1]:
            continue
        kept.append(sp)
    for start, end, inner, block in kept:
        plain = seg[pos:start]
        out.append(_bare_scripts(plain))
        conv = _convert_math(inner)
        out.append(("\n\n" + conv + "\n\n") if block else conv)
        pos = end
    out.append(_bare_scripts(seg[pos:]))
    return "".join(out)


def _bare_scripts(s: str) -> str:
    """Digit-only sub/superscripts outside math spans (H_2O -> H₂O)."""
    s = _BARE_SUB_RE.sub(lambda m: _sub_map(m.group(1) if m.group(1) is not None else m.group(2)), s)
    s = _BARE_SUP_RE.sub(lambda m: _sup_map(m.group(1) if m.group(1) is not None else m.group(2)), s)
    return s


def latex_to_unicode(text: str) -> str:
    """Render LaTeX math in text as readable Unicode (render-only).

    Code fences pass through verbatim. Non-string input returns "".
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    # Cap render input: streaming bubbles call this per frame on the
    # full reply — MB garbage must not jank the UI.
    if len(text) > 100_000:
        text = text[:100_000]
    if "\\" not in text and "_" not in text and "^" not in text and "$" not in text:
        return text  # fast path: nothing TeX-like present
    parts = _FENCE_RE.split(text)
    for i in range(0, len(parts), 2):  # even indices: non-code
        parts[i] = _convert_with_inline_dollars(parts[i])
    return "".join(parts)


def _convert_with_inline_dollars(seg: str) -> str:
    """Handle $...$ (math-looking only) then the rest of the segment."""
    def _repl(m: "re.Match[str]") -> str:
        inner = m.group(1)
        # Currency guard: only treat as math with TeX markers inside.
        if "\\" not in inner and "_" not in inner and "^" not in inner:
            return m.group(0)
        return _convert_math(inner)

    seg = _INLINE_DOLLAR_RE.sub(_repl, seg)
    return _convert_segment(seg)
