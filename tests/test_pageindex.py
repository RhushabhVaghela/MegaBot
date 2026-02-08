"""
Tests for PageIndexRAG
"""

import pytest
import tempfile
import os
from unittest.mock import MagicMock, AsyncMock, patch

from core.rag.pageindex import PageIndexRAG


@pytest.fixture
def temp_dir():
    """Create a temporary directory with test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        os.makedirs(os.path.join(tmpdir, "src"))
        os.makedirs(os.path.join(tmpdir, "docs"))

        # Python file
        with open(os.path.join(tmpdir, "src", "main.py"), "w") as f:
            f.write("""
class Calculator:
    def add(self, a, b):
        return a + b

def main():
    calc = Calculator()
    print(calc.add(2, 3))
""")

        # JavaScript file
        with open(os.path.join(tmpdir, "src", "utils.js"), "w") as f:
            f.write("""
function helper(value) {
    return value * 2;
}

const config = { enabled: true };
""")

        # Markdown file
        with open(os.path.join(tmpdir, "docs", "README.md"), "w") as f:
            f.write("""
# Project Title

This is a test project.

## Features

- Feature 1
- Feature 2
""")

        yield tmpdir


@pytest.fixture
def page_index(temp_dir):
    return PageIndexRAG(temp_dir)


class TestPageIndexRAG:
    """Test PageIndexRAG functionality"""

    def test_init(self, temp_dir):
        """Test initialization"""
        rag = PageIndexRAG(temp_dir, llm=MagicMock())
        assert rag.root_dir == temp_dir
        assert rag.llm is not None
        assert rag.index == {}
        assert rag.index_path == os.path.join(temp_dir, ".megabot_index.json")

    @pytest.mark.asyncio
    async def test_build_index_from_scratch(self, page_index):
        """Test building index from scratch"""
        await page_index.build_index(force_rebuild=True)

        assert "root" in page_index.index
        assert "files" in page_index.index
        assert "folders" in page_index.index

        # Check that files were indexed
        assert "main.py" in page_index.index["folders"]["src"]["files"]
        assert "utils.js" in page_index.index["folders"]["src"]["files"]
        assert "README.md" in page_index.index["folders"]["docs"]["files"]

        # Check that cache was saved
        assert os.path.exists(page_index.index_path)

    @pytest.mark.asyncio
    async def test_build_index_with_cache(self, page_index):
        """Test loading index from cache"""
        # First build and cache
        await page_index.build_index(force_rebuild=True)
        original_index = page_index.index.copy()

        # Reset and load from cache
        page_index.index = {}
        await page_index.build_index(force_rebuild=False)

        assert page_index.index == original_index

    def test_extract_symbols_python(self, page_index):
        """Test symbol extraction for Python files"""
        content = """
class MyClass:
    pass

def my_function():
    pass

# Comment
"""
        symbols = page_index._extract_symbols(content, "test.py")
        assert "MyClass" in symbols
        assert "my_function" in symbols

    def test_extract_symbols_javascript(self, page_index):
        """Test symbol extraction for JS/TS files"""
        content = """
class MyClass {
}

function myFunction() {
}

const myConst = 42;
"""
        symbols = page_index._extract_symbols(content, "test.js")
        assert "MyClass" in symbols
        assert "myFunction" in symbols
        assert "myConst" in symbols

    def test_extract_symbols_markdown(self, page_index):
        """Test symbol extraction for Markdown files"""
        content = """
# Main Title

## Subsection

### Subsubsection
"""
        symbols = page_index._extract_symbols(content, "test.md")
        assert "Main Title" in symbols
        assert "Subsection" in symbols
        assert "Subsubsection" in symbols

    def test_extract_symbols_unknown(self, page_index):
        """Test symbol extraction for unknown file types"""
        content = "Some content"
        symbols = page_index._extract_symbols(content, "test.txt")
        assert symbols == []

    def test_generate_quick_summary(self, page_index):
        """Test quick summary generation"""
        content = """
First line

Second line

Third line

Fourth line
"""
        summary = page_index._generate_quick_summary(content)
        assert "First line" in summary
        assert "Second line" in summary
        assert "Third line" in summary
        assert summary.endswith("...")

    @pytest.mark.asyncio
    async def test_navigate_without_llm(self, page_index):
        """Test navigation without LLM (keyword search)"""
        await page_index.build_index(force_rebuild=True)

        result = await page_index.navigate("Calculator")
        assert "Calculator" in result
        assert "main.py" in result

    @pytest.mark.asyncio
    async def test_navigate_with_llm(self, page_index):
        """Test navigation with LLM"""
        await page_index.build_index(force_rebuild=True)
        page_index.llm = AsyncMock()
        page_index.llm.generate.return_value = '["src/main.py"]'

        with patch.object(page_index, "get_file_context", new_callable=AsyncMock) as mock_context:
            mock_context.return_value = "file content"
            result = await page_index.navigate("find calculator")

            page_index.llm.generate.assert_called_once()
            mock_context.assert_called_once_with("src/main.py")
            assert "src/main.py" in result
            assert "file content" in result

    def test_keyword_navigation(self, page_index):
        """Test keyword-based navigation"""
        # Manually set up index
        page_index.index = {
            "files": {},
            "folders": {
                "src": {
                    "files": {
                        "main.py": {
                            "summary": "Calculator class implementation",
                            "headers": ["Calculator", "main"],
                        }
                    },
                    "folders": {},
                }
            },
        }

        result = page_index._keyword_navigation("Calculator")
        assert "Calculator" in result
        assert "main.py" in result

    def test_keyword_navigation_no_results(self, page_index):
        """Test keyword navigation with no matches"""
        page_index.index = {"files": {}, "folders": {}}
        result = page_index._keyword_navigation("nonexistent")
        assert "No matching files found" in result

    @pytest.mark.asyncio
    async def test_reasoned_navigation_without_llm(self, page_index):
        """Test reasoned navigation fallback without LLM"""
        page_index.llm = None
        result = await page_index._reasoned_navigation("query")
        # Should fall back to keyword navigation
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_reasoned_navigation_with_llm_error(self, page_index):
        """Test reasoned navigation with LLM error"""
        page_index.llm = AsyncMock()
        page_index.llm.generate.side_effect = RuntimeError("LLM error")
        page_index.index = {"files": {}, "folders": {}}

        result = await page_index._reasoned_navigation("query")
        assert "Reasoning RAG failed" in result
        assert "Falling back to keywords" in result

    def test_get_collapsed_index(self, page_index):
        """Test collapsed index generation"""
        page_index.index = {
            "files": {"root.txt": {"summary": "", "headers": []}},
            "folders": {
                "src": {
                    "files": {"main.py": {"summary": "", "headers": []}},
                    "folders": {
                        "sub": {
                            "files": {"deep.py": {"summary": "", "headers": []}},
                            "folders": {},
                        }
                    },
                }
            },
        }

        collapsed = page_index._get_collapsed_index(max_depth=1)
        assert "root.txt" in collapsed["files"]
        assert "src" in collapsed["folders"]
        # Check depth limiting
        assert "note" in collapsed["folders"]["src"]["folders"]["sub"]

    @pytest.mark.asyncio
    async def test_get_file_context(self, temp_dir):
        """Test file context retrieval"""
        rag = PageIndexRAG(temp_dir)
        content = await rag.get_file_context("src/main.py")
        assert "class Calculator" in content
        assert len(content.split("\n")) <= 100

    @pytest.mark.asyncio
    async def test_get_file_context_not_found(self, page_index):
        """Test file context for non-existent file"""
        result = await page_index.get_file_context("nonexistent.py")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_get_file_context_read_error(self, page_index):
        """Test file context with read error"""
        with patch("builtins.open", side_effect=OSError("read error")):
            result = await page_index.get_file_context("src/main.py")
            assert "Error reading file" in result


@pytest.mark.asyncio
async def test_build_index_cache_errors(page_index, temp_dir, caplog):
    """Test cache load and save errors in build_index (lines 28-29, 42-43)"""
    import logging

    page_index.index_path = os.path.join(temp_dir, "error_index.json")

    # 1. Load cache error (lines 28-29)
    with open(page_index.index_path, "w") as f:
        f.write("invalid json")

    with caplog.at_level(logging.DEBUG, logger="core.rag.pageindex"):
        # Should build from scratch if cache load fails
        await page_index.build_index(force_rebuild=False)
        assert any("RAG: Failed to load cache:" in r.message for r in caplog.records)

    caplog.clear()

    # 2. Save cache error (lines 42-43)
    # Re-build to trigger save
    with patch("os.path.exists", return_value=False):
        with patch("builtins.open", side_effect=OSError("Save error")):
            with caplog.at_level(logging.DEBUG, logger="core.rag.pageindex"):
                await page_index.build_index(force_rebuild=True)
                assert any("RAG: Failed to save cache:" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_walk_and_index_read_error(page_index, temp_dir):
    """Test _walk_and_index with file read error (lines 77-78)"""
    # Create a file and make it unreadable
    unreadable_file = os.path.join(temp_dir, "unreadable.py")
    with open(unreadable_file, "w") as f:
        f.write("content")

    with patch("builtins.open", side_effect=OSError("Read error")):
        page_index.index = {"files": {}, "folders": {}}
        page_index._walk_and_index(temp_dir, page_index.index)
        # Should continue and not crash, and file should not be in index
        assert "unreadable.py" not in page_index.index["files"]


@pytest.mark.asyncio
async def test_navigate_auto_build_index(page_index):
    """Test navigate calls build_index if index is empty (line 110)"""
    page_index.index = {}
    with patch.object(page_index, "build_index", new_callable=AsyncMock) as mock_build:
        await page_index.navigate("test")
        mock_build.assert_called_once()


@pytest.mark.asyncio
async def test_reasoned_navigation_no_paths_found(page_index):
    """Test _reasoned_navigation when no paths are found in LLM response (line 165)"""
    page_index.llm = AsyncMock()
    page_index.llm.generate.return_value = "No paths here"
    page_index.index = {
        "files": {"test.py": {"summary": "s", "headers": []}},
        "folders": {},
    }

    with patch.object(page_index, "_keyword_navigation") as mock_keyword:
        await page_index._reasoned_navigation("query")
        mock_keyword.assert_called_once()
