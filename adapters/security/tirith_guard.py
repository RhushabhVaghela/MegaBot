import re
import unicodedata


class TirithGuard:
    """
    Terminal Guard inspired by the Tirith project.
    Protects against ANSI escape injection, homoglyph attacks, and shell
    metacharacter injection in terminal output and commands.
    """

    # Bi-directional control characters used in RLO/homograph attacks.
    # Defined once as a class constant to avoid per-call list allocation.
    _BIDI_CHARS = frozenset(
        (
            "\u202e",  # RLO
            "\u202d",  # LRO
            "\u202b",  # RLE
            "\u202a",  # LRE
            "\u200f",  # RLM
            "\u200e",  # LRM
        )
    )

    # Shell metacharacters that enable command injection when passed to a
    # shell interpreter.  Used by ``validate_command_input`` (VULN-014 fix).
    _SHELL_METACHARS = re.compile(r"[;|&`$(){}<>\\\n\r]")

    # Common shell injection payloads (case-insensitive)
    _SHELL_INJECTION_PATTERNS = re.compile(
        r"(?i)(?:\$\(|`|&&|\|\||>>|<<|/etc/passwd|/etc/shadow|/dev/tcp)",
    )

    def __init__(self):
        # ANSI escape sequence regex
        self.ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def sanitize(self, text: str) -> str:
        """
        Sanitize text for safe display in a terminal or UI.
        """
        if not text:
            return ""

        # 1. Strip ANSI escape sequences
        sanitized = self.ansi_escape.sub("", text)

        # 2. Normalize Unicode to NFC
        sanitized = unicodedata.normalize("NFC", sanitized)

        # 3. Remove dangerous control characters except common ones
        # We allow newline, carriage return, and tab
        sanitized = "".join(ch for ch in sanitized if ch >= " " or ch in "\n\r\t")

        return sanitized

    # Unicode script ranges that contain characters visually confusable with
    # basic Latin (ASCII a-z, A-Z, 0-9).  Only these scripts are flagged —
    # legitimate non-Latin text (CJK, Arabic, Devanagari, emoji, etc.) passes.
    _CONFUSABLE_RANGES = (
        (0x0400, 0x04FF),  # Cyrillic
        (0x0370, 0x03FF),  # Greek and Coptic
        (0x0500, 0x052F),  # Cyrillic Supplement
        (0x2DE0, 0x2DFF),  # Cyrillic Extended-A
        (0xA640, 0xA69F),  # Cyrillic Extended-B
        (0x1C80, 0x1C8F),  # Cyrillic Extended-C
    )

    def check_homoglyphs(self, text: str) -> bool:
        """
        Check if text contains suspicious homoglyphs from scripts that are
        visually confusable with Latin (e.g. Cyrillic 'а' vs Latin 'a').

        Returns True if suspicious characters are found.  Legitimate non-Latin
        text (CJK, accented Latin, emoji, etc.) is NOT flagged.
        """
        has_latin = False
        has_confusable = False
        for char in text:
            cp = ord(char)
            cat = unicodedata.category(char)
            if cat.startswith("Mn") or cat.startswith("Me"):
                continue  # Skip combining marks

            # Check for bi-directional override characters (always suspicious)
            if char in self._BIDI_CHARS:
                return True

            # Track whether we have Latin letters
            if 0x41 <= cp <= 0x5A or 0x61 <= cp <= 0x7A:
                has_latin = True

            # Check confusable script ranges
            for start, end in self._CONFUSABLE_RANGES:
                if start <= cp <= end:
                    has_confusable = True
                    break

        # Only flag if BOTH Latin and confusable-script chars appear together
        # (mixed-script is the actual attack vector for homoglyph phishing)
        return has_latin and has_confusable

    def validate(self, text: str) -> bool:
        """
        Validates if the text (usually a command or URL) is safe.
        Returns False if it contains suspicious characters like Cyrillic or RLO.
        """
        if not text:
            return True

        # Check for Cyrillic characters (Common in homograph attacks)
        # Cyrillic range: \u0400-\u04FF
        if re.search(r"[\u0400-\u04FF]", text):
            return False

        # Check for Right-to-Left Override (RLO) \u202E and other bi-di control chars
        # These can be used to hide extensions (e.g. exe.txt[RLO]cod.bat -> tab.doc.txt.exe)
        return not any(char in text for char in self._BIDI_CHARS)

    def validate_command_input(self, text: str) -> bool:
        """Validate that *text* is safe to use as a command argument.

        Returns ``False`` if the string contains shell metacharacters or
        common injection payloads (VULN-014 fix).
        """
        if not text:
            return True

        # Reject shell metacharacters
        if self._SHELL_METACHARS.search(text):
            return False

        # Reject known injection payloads
        if self._SHELL_INJECTION_PATTERNS.search(text):
            return False

        return self.validate(text)

    def wrap_output(self, output: str) -> str:
        """
        Helper to wrap terminal output with sanitization.
        """
        return self.sanitize(output)


# Singleton instance for easy access
guard = TirithGuard()
