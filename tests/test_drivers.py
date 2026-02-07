"""
Tests for ComputerDriver
"""

import pytest
import base64
import io
from unittest.mock import MagicMock, patch
from PIL import Image

from core.drivers import ComputerDriver


@pytest.fixture
def driver():
    return ComputerDriver(width=800, height=600)


class TestComputerDriver:
    """Test ComputerDriver functionality"""

    def test_init(self):
        """Test initialization"""
        driver = ComputerDriver(width=1024, height=768)
        assert driver.width == 1024
        assert driver.height == 768

    def test_get_pyautogui_with_import(self, driver):
        """Test _get_pyautogui when pyautogui is available"""
        with patch.dict("sys.modules", {"pyautogui": MagicMock()}):
            pg = driver._get_pyautogui()
            assert pg.FAILSAFE is True

    def test_get_pyautogui_mock_fallback(self, driver):
        """Test _get_pyautogui fallback to mock"""
        with patch.dict("sys.modules", {}, clear=True):
            pg = driver._get_pyautogui()
            assert hasattr(pg, "moveTo")
            assert hasattr(pg, "click")
            assert hasattr(pg, "write")

    @pytest.mark.asyncio
    async def test_execute_mouse_move(self, driver):
        """Test mouse move action"""
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_get_pg.return_value = mock_pg

            result = await driver.execute("mouse_move", coordinate=[100, 200])
            mock_pg.moveTo.assert_called_once_with(100, 200)
            assert "Moved mouse to [100, 200]" in result

    @pytest.mark.asyncio
    async def test_execute_left_click(self, driver):
        """Test left click action"""
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_get_pg.return_value = mock_pg

            result = await driver.execute("left_click")
            mock_pg.click.assert_called_once()
            assert "Left clicked" in result

    @pytest.mark.asyncio
    async def test_execute_right_click(self, driver):
        """Test right click action"""
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_get_pg.return_value = mock_pg

            result = await driver.execute("right_click")
            mock_pg.rightClick.assert_called_once()
            assert "Right clicked" in result

    @pytest.mark.asyncio
    async def test_execute_type(self, driver):
        """Test typing action"""
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_get_pg.return_value = mock_pg

            result = await driver.execute("type", text="hello world")
            mock_pg.write.assert_called_once_with("hello world")
            assert "Typed: hello world" in result

    @pytest.mark.asyncio
    async def test_execute_key(self, driver):
        """Test key press action"""
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_get_pg.return_value = mock_pg

            result = await driver.execute("key", text="enter")
            mock_pg.press.assert_called_once_with("enter")
            assert "Pressed key: enter" in result

    @pytest.mark.asyncio
    async def test_execute_screenshot(self, driver):
        """Test screenshot action"""
        with patch.object(driver, "take_screenshot") as mock_screenshot:
            mock_screenshot.return_value = "base64_data"

            result = await driver.execute("screenshot")
            mock_screenshot.assert_called_once()
            assert result == "base64_data"

    @pytest.mark.asyncio
    async def test_execute_analyze_image(self, driver):
        """Test analyze image action"""
        with patch.object(driver, "analyze_image") as mock_analyze:
            mock_analyze.return_value = "analysis_result"

            result = await driver.execute("analyze_image", text="image_data")
            mock_analyze.assert_called_once_with("image_data")
            assert result == "analysis_result"

    @pytest.mark.asyncio
    async def test_execute_blur_regions(self, driver):
        """Test blur regions action"""
        regions = [{"x": 10, "y": 10, "width": 50, "height": 50}]
        with patch.object(driver, "blur_regions") as mock_blur:
            mock_blur.return_value = "blurred_data"

            result = await driver.execute("blur_regions", text="image_data", regions=regions)
            mock_blur.assert_called_once_with("image_data", regions)
            assert result == "blurred_data"

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, driver):
        """Test unknown action"""
        result = await driver.execute("unknown_action")
        assert "not implemented" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_missing_parameters(self, driver):
        """Test action with missing parameters"""
        result = await driver.execute("type")  # Missing text
        assert "not implemented or missing parameters" in result

    @pytest.mark.asyncio
    async def test_execute_error_handling(self, driver):
        """Test error handling in execute"""
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_pg.moveTo.side_effect = Exception("Mock error")
            mock_get_pg.return_value = mock_pg

            result = await driver.execute("mouse_move", coordinate=[100, 200])
            assert "Error executing mouse_move: Mock error" in result

    @pytest.mark.asyncio
    async def test_analyze_image(self, driver):
        """Test image analysis raises NotImplementedError (no vision model configured)"""
        with pytest.raises(NotImplementedError, match="vision model"):
            await driver.analyze_image("dummy_data")

    def test_blur_regions(self, driver):
        """Test blurring regions in image"""
        # Create a test image
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        regions = [{"x": 10, "y": 10, "width": 20, "height": 20}]

        result = driver.blur_regions(img_base64, regions)
        # Should return base64 string
        assert isinstance(result, str)
        # Decode to verify it's valid base64
        decoded = base64.b64decode(result)
        # Should be able to open as image
        blurred_img = Image.open(io.BytesIO(decoded))
        assert blurred_img.size == (100, 100)

    def test_blur_regions_empty_regions(self, driver):
        """Test blurring with empty regions list"""
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        regions = []

        result = driver.blur_regions(img_base64, regions)
        # Should still return valid base64
        assert isinstance(result, str)

    def test_take_screenshot_mock(self, driver):
        """Test screenshot with mock pyautogui"""
        mock_img = Image.new("RGB", (1024, 768), (0, 0, 0))
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_pg.screenshot.return_value = mock_img
            mock_get_pg.return_value = mock_pg

            result = driver.take_screenshot()
            assert isinstance(result, str)
            # Should be base64
            decoded = base64.b64decode(result)
            screenshot_img = Image.open(io.BytesIO(decoded))
            assert screenshot_img.size == (800, 600)  # Should be resized

    def test_take_screenshot_no_resize(self, driver):
        """Test screenshot when no resize needed"""
        driver.width = 1024
        driver.height = 768
        mock_img = Image.new("RGB", (1024, 768), (0, 0, 0))
        with patch.object(driver, "_get_pyautogui") as mock_get_pg:
            mock_pg = MagicMock()
            mock_pg.screenshot.return_value = mock_img
            mock_get_pg.return_value = mock_pg

            result = driver.take_screenshot()
            decoded = base64.b64decode(result)
            screenshot_img = Image.open(io.BytesIO(decoded))
            assert screenshot_img.size == (1024, 768)  # No resize

    def test_mock_pyautogui_methods(self, driver):
        """Test methods of MockPyAutoGUI (lines 25, 28, 31, 34, 37, 40-41)"""
        with patch.dict("sys.modules", {"pyautogui": None}):
            pg = driver._get_pyautogui()

            # These just print, but we want to cover the lines
            pg.moveTo(100, 100)
            pg.click()
            pg.rightClick()
            pg.write("test")
            pg.press("enter")

            img = pg.screenshot()
            assert isinstance(img, Image.Image)
            assert img.size == (1024, 768)


@pytest.mark.asyncio
async def test_drivers_mopup():
    from core.drivers import ComputerDriver
    from PIL import Image
    import base64
    import io

    driver = ComputerDriver()

    # Test blur_regions
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    regions = [{"x": 10, "y": 10, "width": 20, "height": 20}]
    res = driver.blur_regions(img_b64, regions)
    assert len(res) > 0

    # Test execute mouse_move
    res = await driver.execute("mouse_move", coordinate=[100, 100])
    assert "Moved mouse" in res

    # Test execute type
    res = await driver.execute("type", text="hello")
    assert "Typed: hello" in res

    # Test execute key
    res = await driver.execute("key", text="enter")
    assert "Pressed key: enter" in res
