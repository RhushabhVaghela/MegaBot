import functools
import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("megabot.instrumentation")


def track_telemetry(func) -> Callable:
    """
    Decorator to track latency, token usage, and other metadata for LLM calls.
    Ports patterns from agent-lightning for high-precision observability.
    """

    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs) -> Any:
        start_time = time.perf_counter()

        # Try to capture prompt/messages for context
        _prompt = kwargs.get("prompt") or (args[0] if args else None)
        _messages = kwargs.get("messages")
        model = getattr(self, "model", "unknown")

        try:
            result = await func(self, *args, **kwargs)
            latency = time.perf_counter() - start_time

            metadata = {
                "provider": self.__class__.__name__,
                "model": model,
                "latency_sec": round(latency, 4),
            }

            # Extraction logic for different result formats
            if isinstance(result, dict):
                # OpenAI / OpenRouter / Groq / etc.
                usage = result.get("usage", {})
                if usage:
                    metadata.update(
                        {
                            "prompt_tokens": usage.get("prompt_tokens"),
                            "completion_tokens": usage.get("completion_tokens"),
                            "total_tokens": usage.get("total_tokens"),
                        }
                    )

                # Ported from agent-lightning: Capture raw token IDs if provider supports it
                # (Often available in vLLM or specialized deployments)
                if "prompt_token_ids" in result:
                    metadata["prompt_token_ids"] = result["prompt_token_ids"]

                # Check choices for response token ids
                choices = result.get("choices", [])
                if choices and isinstance(choices, list) and len(choices) > 0:
                    first_choice = choices[0]
                    if "response_token_ids" in first_choice:
                        metadata["response_token_ids"] = first_choice["response_token_ids"]
                    elif "token_ids" in first_choice:
                        metadata["response_token_ids"] = first_choice["token_ids"]

            elif isinstance(result, list) and len(result) > 0:
                # Anthropic / Gemini specific tool-use lists
                # We can't easily get tokens here without more parsing or separate usage fields
                pass

            logger.info("[TELEMETRY] %s", json.dumps(metadata))
            return result

        except Exception as e:
            latency = time.perf_counter() - start_time
            logger.error(
                "[TELEMETRY_ERROR] Provider: %s, Error: %s, Latency: %ss",
                self.__class__.__name__,
                e,
                round(latency, 4),
            )
            raise e

    return wrapper
