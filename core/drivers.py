import base64
import io
import json
from PIL import Image, ImageFilter
from typing import Dict, Optional, List


class ComputerDriver:
    def __init__(self, width: int = 1024, height: int = 768):
        self.width = width
        self.height = height

    def _get_pyautogui(self):
        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            return pyautogui
        except (ImportError, Exception, SystemExit):
            # Mock for headless environments
            class MockPyAutoGUI:
                FAILSAFE = True

                def moveTo(self, x, y):
                    print(f"Headless Mock: Moving mouse to ({x}, {y})")

                def click(self):
                    print("Headless Mock: Clicking")

                def rightClick(self):
                    print("Headless Mock: Right-clicking")

                def write(self, text):
                    print(f"Headless Mock: Typing '{text}'")

                def press(self, key):
                    print(f"Headless Mock: Pressing '{key}'")

                def screenshot(self):
                    print("Headless Mock: Taking screenshot")
                    return Image.new("RGB", (1024, 768), (0, 0, 0))

            return MockPyAutoGUI()

    async def execute(
        self,
        action: str,
        coordinate: Optional[list] = None,
        text: Optional[str] = None,
        regions: Optional[List[Dict[str, int]]] = None,
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
            elif action == "blur_regions":
                if text and regions:
                    return self.blur_regions(text, regions)

            return f"Action {action} not implemented or missing parameters"
        except Exception as e:
            return f"Error executing {action}: {e}"

    async def analyze_image(self, image_data: str) -> str:
        """
        Analyze an image using a vision model (e.g. Claude 3.5 Vision, GPT-4o).

        Args:
            image_data: Base64-encoded image data

        Returns:
            JSON string with analysis results including bounding boxes

        Raises:
            NotImplementedError: Vision model integration not yet implemented
        """
        raise NotImplementedError(
            "analyze_image requires a vision model integration (e.g. Claude 3.5 Vision, GPT-4o). "
            "See docs/developer_notes.md for implementation guidance."
        )

    def blur_regions(self, image_base64: str, regions: List[Dict[str, int]]) -> str:
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
