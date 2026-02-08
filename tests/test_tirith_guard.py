"""Tests for Tirith Guard security module"""

from megabot.adapters.security.tirith_guard import TirithGuard, guard


class TestTirithGuard:
    """Test suite for TirithGuard security validator"""

    def test_sanitize_empty_string(self):
        """Test sanitizing empty string"""
        tg = TirithGuard()
        assert tg.sanitize("") == ""
        assert tg.sanitize(None) == ""

    def test_sanitize_ansi_escape_sequences(self):
        """Test removing ANSI escape sequences"""
        tg = TirithGuard()
        # ANSI color codes
        text = "\x1b[31mRed Text\x1b[0m"
        assert tg.sanitize(text) == "Red Text"

        # ANSI cursor movement
        text = "\x1b[2J\x1b[HClear screen"
        assert tg.sanitize(text) == "Clear screen"

    def test_sanitize_unicode_normalization(self):
        """Test Unicode normalization"""
        tg = TirithGuard()
        # Combined character vs decomposed
        text = "caf\u0065\u0301"  # cafe with combining acute accent
        result = tg.sanitize(text)
        assert "caf" in result

    def test_sanitize_control_characters(self):
        """Test removing dangerous control characters"""
        tg = TirithGuard()
        # Bell character
        text = "Hello\x07World"
        assert tg.sanitize(text) == "HelloWorld"

        # Null byte
        text = "Hello\x00World"
        assert tg.sanitize(text) == "HelloWorld"

    def test_sanitize_allows_safe_whitespace(self):
        """Test that safe whitespace is preserved"""
        tg = TirithGuard()
        text = "Line 1\nLine 2\tTabbed\r\nWindows"
        result = tg.sanitize(text)
        assert "\n" in result
        assert "\t" in result
        assert "\r" in result

    def test_check_homoglyphs_ascii_only(self):
        """Test homoglyph check with ASCII only"""
        tg = TirithGuard()
        text = "Hello World 123"
        assert tg.check_homoglyphs(text) is False

    def test_check_homoglyphs_with_cyrillic(self):
        """Test detecting Cyrillic homoglyphs"""
        tg = TirithGuard()
        # Cyrillic 'а' (U+0430) instead of Latin 'a' (U+0061)
        text = "p\u0430ypal.com"  # looks like paypal.com
        assert tg.check_homoglyphs(text) is True

    def test_check_homoglyphs_with_greek(self):
        """Test detecting Greek homoglyphs"""
        tg = TirithGuard()
        # Greek 'ο' (U+03BF) instead of Latin 'o' (U+006F)
        text = "g\u03bfogle.com"  # looks like google.com
        assert tg.check_homoglyphs(text) is True

    def test_validate_empty_string(self):
        """Test validating empty string"""
        tg = TirithGuard()
        assert tg.validate("") is True
        assert tg.validate(None) is True

    def test_validate_safe_text(self):
        """Test validating safe text"""
        tg = TirithGuard()
        text = "Hello World! This is safe."
        assert tg.validate(text) is True

    def test_validate_cyrillic_characters(self):
        """Test detecting Cyrillic characters"""
        tg = TirithGuard()
        # Text with Cyrillic characters
        text = "Hello \u041f\u0440\u0438\u0432\u0435\u0442"  # Hello Привет
        assert tg.validate(text) is False

    def test_validate_rlo_character(self):
        """Test detecting Right-to-Left Override"""
        tg = TirithGuard()
        # RLO character can be used to spoof file extensions
        text = "filename.txt\u202eexe.bat"
        assert tg.validate(text) is False

    def test_validate_lro_character(self):
        """Test detecting Left-to-Right Override"""
        tg = TirithGuard()
        text = "filename\u202dspoofed"
        assert tg.validate(text) is False

    def test_validate_rle_character(self):
        """Test detecting Right-to-Left Embedding"""
        tg = TirithGuard()
        text = "filename\u202bspoofed"
        assert tg.validate(text) is False

    def test_validate_lre_character(self):
        """Test detecting Left-to-Right Embedding"""
        tg = TirithGuard()
        text = "filename\u202aspoofed"
        assert tg.validate(text) is False

    def test_validate_rlm_character(self):
        """Test detecting Right-to-Left Mark"""
        tg = TirithGuard()
        text = "filename\u200fspoofed"
        assert tg.validate(text) is False

    def test_validate_lrm_character(self):
        """Test detecting Left-to-Right Mark"""
        tg = TirithGuard()
        text = "filename\u200espoofed"
        assert tg.validate(text) is False

    def test_wrap_output(self):
        """Test wrap_output helper method"""
        tg = TirithGuard()
        text = "\x1b[31mColored\x1b[0m \x07Bell"
        result = tg.wrap_output(text)
        assert result == "Colored Bell"

    def test_check_homoglyphs_with_combining_marks(self):
        """Test homoglyph check with combining marks (line 43 coverage)"""
        tg = TirithGuard()
        # Combining acute accent is Mn category
        text = "e\u0301"
        # check_homoglyphs should skip the accent and return False because 'e' is < 127
        assert tg.check_homoglyphs(text) is False


class TestTirithGuardSingleton:
    """Test singleton instance"""

    def test_singleton_exists(self):
        """Test that singleton guard exists"""
        assert guard is not None
        assert isinstance(guard, TirithGuard)

    def test_singleton_sanitize(self):
        """Test using singleton for sanitization"""
        text = "\x1b[31mTest\x1b[0m"
        result = guard.sanitize(text)
        assert result == "Test"

    def test_singleton_validate(self):
        """Test using singleton for validation"""
        assert guard.validate("Safe text") is True
        assert guard.validate("\u202eUnsafe") is False


class TestValidateCommandInput:
    """Test suite for TirithGuard.validate_command_input (Phase 3C / VULN-014)"""

    def setup_method(self):
        self.tg = TirithGuard()

    def test_empty_string(self):
        """Empty string is valid"""
        assert self.tg.validate_command_input("") is True

    def test_clean_text(self):
        """Normal text passes validation"""
        assert self.tg.validate_command_input("hello world") is True

    def test_shell_metachar_semicolon(self):
        """Semicolon enables command chaining"""
        assert self.tg.validate_command_input("rm -rf ; ls") is False

    def test_shell_metachar_pipe(self):
        """Pipe enables command piping"""
        assert self.tg.validate_command_input("cat file | grep") is False

    def test_shell_metachar_ampersand(self):
        """Ampersand enables background execution"""
        assert self.tg.validate_command_input("cmd &") is False

    def test_shell_metachar_backtick(self):
        """Backtick enables command substitution"""
        assert self.tg.validate_command_input("echo `whoami`") is False

    def test_shell_metachar_dollar(self):
        """Dollar sign enables variable expansion"""
        assert self.tg.validate_command_input("echo $HOME") is False

    def test_injection_dollar_paren(self):
        """$(cmd) is a command substitution injection"""
        assert self.tg.validate_command_input("$(whoami)") is False

    def test_injection_double_ampersand(self):
        """&& enables conditional command chaining"""
        assert self.tg.validate_command_input("cmd1 && cmd2") is False

    def test_injection_etc_passwd(self):
        """/etc/passwd is a common file read target"""
        assert self.tg.validate_command_input("cat /etc/passwd") is False

    def test_cyrillic_homoglyph(self):
        """Cyrillic characters should be rejected (homoglyph attack via validate())"""
        # Cyrillic 'е' (U+0435) looks like Latin 'e'
        assert self.tg.validate_command_input("h\u0435llo") is False

    def test_bidi_char(self):
        """Bi-directional override chars should be rejected (via validate())"""
        assert self.tg.validate_command_input("safe\u202efile.txt") is False

    def test_newline_injection(self):
        """Newline in input enables command injection"""
        assert self.tg.validate_command_input("cmd\nrm -rf /") is False

    def test_carriage_return_injection(self):
        """Carriage return in input enables injection"""
        assert self.tg.validate_command_input("cmd\rrm -rf /") is False
