"""
Groq LLM client with key + model rotation.
Slots are ordered by TPD/RPM descending — biggest buckets used first.
On 429 / rate-limit, automatically advances to next slot.

Slot order (9 total):
  Key1 + llama-3.1-8b-instant   (~131K TPM, 14.4K RPD)
  Key2 + llama-3.1-8b-instant
  Key3 + llama-3.1-8b-instant
  Key1 + gemma2-9b-it           (~15K TPM,  14.4K RPD)
  Key2 + gemma2-9b-it
  Key3 + gemma2-9b-it
  Key1 + llama-3.3-70b-versatile (~6K TPM,  1K RPD — best quality)
  Key2 + llama-3.3-70b-versatile
  Key3 + llama-3.3-70b-versatile
"""

import os
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Models ordered by TPD/RPM descending (highest limits first)
_MODELS: list[tuple[str, int, int]] = [
    # (model_id, approx_rpm, approx_tpd)
    ("llama-3.1-8b-instant",     30, 131_072 * 1_440),
    ("gemma2-9b-it",             30,  15_000 * 1_440),
    ("llama-3.3-70b-versatile",  30,   6_000 * 1_440),
]

_KEY_VARS = ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3")


def _load_keys() -> list[str]:
    return [os.getenv(v, "").strip() for v in _KEY_VARS if os.getenv(v, "").strip()]


def _build_slots(keys: list[str]) -> list[tuple[str, str]]:
    """Keys rotate within each model tier: key1→key2→key3, then next model."""
    slots = []
    for model_id, _, _ in _MODELS:
        for key in keys:
            slots.append((key, model_id))
    return slots


class GroqRotatingClient:
    """
    Wraps Groq with automatic key + model rotation.
    Rotates to next slot on RateLimitError or any API error.
    """

    def __init__(self):
        self._keys = _load_keys()
        if not self._keys:
            raise RuntimeError(
                "No Groq API key found. Set GROQ_API_KEY in your .env file."
            )
        self._slots = _build_slots(self._keys)
        self._slot_idx = 0
        log.info(f"[GroqClient] {len(self._slots)} slots loaded "
                 f"({len(self._keys)} keys × {len(_MODELS)} models)")

    def _advance(self):
        self._slot_idx = (self._slot_idx + 1) % len(self._slots)

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> str:
        """Send a chat request. Rotates key+model on rate-limit. Returns text."""
        from groq import Groq, RateLimitError  # local import — groq optional dep

        tried = 0
        last_err: Optional[Exception] = None

        while tried < len(self._slots):
            key, model = self._slots[self._slot_idx]
            try:
                client = Groq(api_key=key)
                kwargs: dict = dict(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                resp = client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content.strip()
                log.debug(f"[GroqClient] OK  slot={self._slot_idx} "
                          f"key=...{key[-6:]} model={model}")
                return text

            except RateLimitError as e:
                log.warning(f"[GroqClient] 429 key=...{key[-6:]} model={model} → next slot")
                last_err = e
                self._advance()
                tried += 1
                time.sleep(0.3)

            except Exception as e:
                log.warning(f"[GroqClient] ERR key=...{key[-6:]} model={model}: {e} → next slot")
                last_err = e
                self._advance()
                tried += 1

        raise RuntimeError(f"All {len(self._slots)} Groq slots exhausted. Last: {last_err}")


# ── Module-level singleton ──────────────────────────────────────────────────────

_client: Optional[GroqRotatingClient] = None


def get_client() -> GroqRotatingClient:
    global _client
    if _client is None:
        _client = GroqRotatingClient()
    return _client


def ask(
    prompt: str,
    system: str = "You are a professional Forex trading assistant for ForgeX AI.",
    max_tokens: int = 512,
    temperature: float = 0.1,
    json_mode: bool = False,
) -> str:
    """Single-turn convenience wrapper: prompt → response text."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]
    return get_client().chat(
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
    )
