"""
LLM Client for FOMO Radio
Supports OpenAI, DeepSeek, and OpenRouter (OpenAI-compatible API).
"""
from typing import Any, Dict, Callable
from openai import OpenAI


class LLMClient:
    """
    LLM Wrapper for various model providers.
    Supports: OpenAI, DeepSeek, OpenRouter
    """

    provider: str = None
    model: str = None

    def __init__(self, llm_config: Dict, api_key: str = None):
        self.provider = llm_config.get("provider", "openai")
        self.model = llm_config.get("model", "gpt-4o-mini")
        self.api_key = api_key

    def initialize_client(self) -> Any:
        """
        Initialize the appropriate LLM client based on provider config.
        Returns (client_class, interact_function).
        """
        if self.provider == "deepseekai":
            return OpenAI, self.interact_deepseekai
        elif self.provider == "openrouter":
            return OpenAI, self.interact_openrouter
        else:
            # Default: OpenAI
            return OpenAI, self.interact_openai

    def interact_openai(self, llm_client: Callable, prompt: str) -> str:
        """Interact with OpenAI API."""
        with llm_client(api_key=self.api_key) as client:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Provide me the script for the show"},
            ]
            completion = client.chat.completions.create(
                model=self.model, messages=messages, timeout=120
            )
            choice = completion.choices[0] if len(completion.choices) > 0 else None
            return choice.message.content if choice else ""

    def interact_deepseekai(self, llm_client: Callable, prompt: str) -> str:
        """Interact with DeepSeek API."""
        with llm_client(
            api_key=self.api_key, base_url="https://api.deepseek.com"
        ) as client:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Provide me the script for the show"},
            ]
            completion = client.chat.completions.create(
                model=self.model, messages=messages, timeout=120
            )
            choice = completion.choices[0] if len(completion.choices) > 0 else None
            return choice.message.content if choice else ""

    def interact_openrouter(self, llm_client: Callable, prompt: str) -> str:
        """Interact with OpenRouter API (OpenAI-compatible)."""
        base_url = "https://openrouter.ai/api/v1"
        with llm_client(
            api_key=self.api_key, base_url=base_url
        ) as client:
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Provide me the script for the show"},
            ]
            completion = client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=120,
                extra_headers={
                    "HTTP-Referer": "https://github.com/CryptoSI-DAO/FOMO-Framework",
                    "X-Title": "FOMO Radio - The Data Drop",
                },
            )
            choice = completion.choices[0] if len(completion.choices) > 0 else None
            return choice.message.content if choice else ""
