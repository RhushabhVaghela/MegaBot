import base64
import io
import logging

from typing import Any

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)


class ComputerDriver:
    def __init__(self, width: int = 1024, height: int = 768):
        self.width = width
        self.height = height

    def _get_pyautogui(self) -> Any:
        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            return pyautogui
        except (ImportError, Exception, SystemExit):
            # Mock for headless environments
            class MockPyAutoGUI:
                FAILSAFE = True

                def moveTo(self, x, y) -> None:
                    logger.debug("Headless Mock: Moving mouse to (%s, %s)", x, y)

                def click(self) -> None:
                    logger.debug("Headless Mock: Clicking")

                def rightClick(self) -> None:
                    logger.debug("Headless Mock: Right-clicking")

                def write(self, text) -> None:
                    logger.debug("Headless Mock: Typing '%s'", text)

                def press(self, key) -> None:
                    logger.debug("Headless Mock: Pressing '%s'", key)

                def screenshot(self) -> Image.Image:
                    logger.debug("Headless Mock: Taking screenshot")
                    return Image.new("RGB", (1024, 768), (0, 0, 0))

            return MockPyAutoGUI()

    async def execute(
        self,
        action: str,
        coordinate: list | None = None,
        text: str | None = None,
        regions: list[dict[str, int]] | None = None,
    ) -> str:
        """Execute a computer action using pyautogui"""
        pg = self._get_pyautogui()
        try:
            if action == "mouse_move":
                if coordinate:
                    pg.moveTo(coordinate[0], coordinate[1])
                    return f"Moved mouse to {coordinate}"
            elif action == "left_click":
                pg.click()
                return "Left clicked"
            elif action == "right_click":
                pg.rightClick()
                return "Right clicked"
            elif action == "type":
                if text:
                    pg.write(text)
                    return f"Typed: {text}"
            elif action == "key":
                if text:
                    pg.press(text)
                    return f"Pressed key: {text}"
            elif action == "screenshot":
                return self.take_screenshot()
            elif action == "analyze_image":
                if text:  # Assuming 'text' contains the base64 or path
                    return await self.analyze_image(text)
            elif action == "blur_regions" and text and regions:
                return self.blur_regions(text, regions)

            return f"Action {action} not implemented or missing parameters"
        except (OSError, ValueError, RuntimeError) as e:
            return f"Error executing {action}: {e}"

    async def analyze_image(self, image_data: str) -> str:
        """
        Analyze an image using a vision model (e.g. Claude 3.5 Vision, GPT-4o).

        Args:
            image_data: Base64-encoded image data

        Returns:
            JSON string with analysis results including bounding boxes
        """
        import json as _json

        # Decode and get basic image metadata as a fallback analysis
        try:
            img_bytes = base64.b64decode(image_data)
            img = Image.open(io.BytesIO(img_bytes))
            width, height = img.size
            mode = img.mode
            fmt = img.format or "unknown"
        except (ValueError, OSError) as e:
            return _json.dumps({"error": f"Failed to decode image: {e}", "bounding_boxes": []})

        logger.warning("[ComputerDriver] analyze_image: vision model not configured, returning image metadata only.")
        return _json.dumps(
            {
                "description": "Vision model not configured. Returning metadata only.",
                "width": width,
                "height": height,
                "mode": mode,
                "format": fmt,
                "bounding_boxes": [],
            }
        )

    def blur_regions(self, image_base64: str, regions: list[dict[str, int]]) -> str:
        """Blur specific rectangular regions in an image"""
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))

        for region in regions:
            x = region.get("x", 0)
            y = region.get("y", 0)
            w = region.get("width", 0)
            h = region.get("height", 0)

            if w > 0 and h > 0:
                # Extract the region
                box = (x, y, x + w, y + h)
                ic = img.crop(box)
                # Apply heavy blur
                for _ in range(5):
                    ic = ic.filter(ImageFilter.GaussianBlur(radius=10))
                # Paste back
                img.paste(ic, box)

        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def take_screenshot(self) -> str:
        """Capture screen and return as base64 string"""
        pg = self._get_pyautogui()
        screenshot = pg.screenshot()
        # Scale if necessary
        if screenshot.width != self.width or screenshot.height != self.height:
            screenshot = screenshot.resize((self.width, self.height))

        buffered = io.BytesIO()
        screenshot.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
