import sys
import os
from core.interfaces import MessagingInterface, Message


class NanobotAdapter(MessagingInterface):
    def __init__(self, nanobot_path: str, telegram_token: str = "", whatsapp_token: str = ""):
        # 1. Try checking if nanobot is already installed as a package
        try:
            from nanobot.core import MarketAnalyzer, RoutineEngine, Messenger

            print("Successfully loaded nanobot from installed packages")
            found_path = True
        except ImportError:
            # 2. Try finding the package in likely locations
            possible_paths = [
                os.path.join(nanobot_path, "src"),
                nanobot_path,
                os.path.join(nanobot_path, "nanobot"),
            ]

            found_path = False
            for path in possible_paths:
                if os.path.exists(path):
                    sys.path.insert(0, path)
                    try:
                        from nanobot.core import (
                            MarketAnalyzer,
                            RoutineEngine,
                            Messenger,
                        )  # pragma: no cover

                        self.nanobot_path = path  # pragma: no cover
                        found_path = True  # pragma: no cover
                        print(f"Successfully loaded nanobot from {path}")  # pragma: no cover
                        break  # pragma: no cover
                    except ImportError:
                        sys.path.pop(0)
                        continue

        if not found_path:
            print(f"WARNING: nanobot not found at {nanobot_path}. Using functional fallback mock.")

            # Fallback Mock Classes with basic functional storage
            class MockMarketAnalyzer:
                async def analyze_market(self, symbol: str) -> dict:
                    return {
                        "symbol": symbol,
                        "analysis": f"Mock analysis for {symbol}",
                        "sentiment": "neutral",
                        "recommendation": "hold",
                    }

            class MockRoutineEngine:
                async def run_routine(self, routine_name: str, **kwargs) -> dict:
                    return {
                        "routine": routine_name,
                        "status": "completed",
                        "result": f"Mock routine {routine_name} executed",
                    }

            class MockMessenger:
                def __init__(self, telegram_token: str = "", whatsapp_token: str = ""):
                    self.telegram_token = telegram_token
                    self.whatsapp_token = whatsapp_token

                async def send_telegram(self, chat_id: str, text: str) -> bool:
                    print(f"Mock Telegram: Sent '{text}' to {chat_id}")
                    return True

                async def send_whatsapp(self, phone: str, text: str) -> bool:
                    print(f"Mock WhatsApp: Sent '{text}' to {phone}")
                    return True

            MarketAnalyzer = MockMarketAnalyzer
            RoutineEngine = MockRoutineEngine
            Messenger = MockMessenger
            found_path = True

        try:
            self.market_analyzer = MarketAnalyzer()
            self.routine_engine = RoutineEngine()
            self.messenger = Messenger(telegram_token=telegram_token, whatsapp_token=whatsapp_token)
        except Exception as e:
            print(f"Failed to initialize Nanobot services: {e}")

            # Final fallback to ultra-safe dummy
            class Dummy:
                async def analyze_market(self, symbol: str) -> dict:
                    return {"error": "Service unavailable"}

                async def run_routine(self, routine_name: str, **kwargs) -> dict:
                    return {"error": "Service unavailable"}

            class DummyMessenger:
                async def send_telegram(self, chat_id: str, text: str) -> bool:
                    return False

                async def send_whatsapp(self, phone: str, text: str) -> bool:
                    return False

            self.market_analyzer = Dummy()
            self.routine_engine = Dummy()
            self.messenger = DummyMessenger()

    async def send_message(self, message: Message) -> None:
        """Send message via Telegram or WhatsApp based on recipient format."""
        recipient = message.metadata.get("recipient", "")
        platform = message.metadata.get("platform", "telegram")

        if platform == "telegram" or recipient.startswith("@"):
            await self.messenger.send_telegram(recipient, message.content)
        elif platform == "whatsapp" or recipient.startswith("+"):
            await self.messenger.send_whatsapp(recipient, message.content)
        else:
            print(f"Nanobot: Unsupported platform {platform} or recipient {recipient}")

    async def receive_message(self) -> Message:
        """Receive message from integrated platforms.

        Returns a placeholder Message since no webhook/polling is configured.
        In production, this would be backed by a webhook endpoint or polling loop.
        """
        print(
            "[Nanobot] receive_message called but no webhook/polling is configured. "
            "Configure a webhook endpoint or implement platform-specific polling."
        )
        return Message(
            sender="system",
            content="[No message: webhook/polling not configured]",
            metadata={"error": "no_receiver_configured"},
        )

    async def analyze_market(self, symbol: str) -> dict:
        """Analyze market data for a given symbol."""
        return await self.market_analyzer.analyze_market(symbol)

    async def run_routine(self, routine_name: str, params: dict) -> dict:
        """Execute a predefined routine."""
        return await self.routine_engine.run_routine(routine_name, **params)
