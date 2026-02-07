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

    def check_homoglyphs(self, text: str) -> bool:
        """
        Check if text contains suspicious homoglyphs (e.g. Cyrillic 'а' instead of Latin 'a').
        Returns True if suspicious homoglyphs are found.
        """
        for char in text:
            if unicodedata.category(char).startswith("Mn") or unicodedata.category(
                char
            ).startswith("Me"):
                continue  # Skip non-spacing marks

            # This is a very basic check. Real Tirith uses punycode comparison.
            # Here we just check for non-ASCII characters that might be used for phishing.
            if ord(char) > 127:
                # If it's not a common localized character (this part is hard to get right without a library)
                # we flag it as suspicious for high-security environments.
                return True
        return False

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
        if any(char in text for char in self._BIDI_CHARS):
            return False

        return True

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
