"""
Telegram Consumer Client for FOMO Radio
Sends voice messages and text to Telegram via Bot API.
"""
from typing import Tuple, Union
import requests
import os


class TelegramConsumerClient:
    """
    Consumer Wrapper for Telegram Bot API.
    Sends voice messages and text to a specified chat.
    """

    source: str = "telegram"
    base_url: str = "https://api.telegram.org/bot{token}"

    def __init__(self, bot_token: str, chat_id: str):
        """
        Initialize Telegram consumer.
        :param bot_token: Telegram Bot API token
        :param chat_id: Target chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = self.base_url.format(token=bot_token)

    def send_text(self, text: str) -> Tuple[bool, Union[str, None]]:
        """
        Send a text message to Telegram.
        :param text: Message text
        :return: (success, error_message)
        """
        try:
            url = f"{self.api_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                return True, None
            return False, f"HTTP {response.status_code}: {response.text}"
        except Exception as e:
            return False, str(e)

    def send_voice(self, voice_path: str) -> Tuple[bool, Union[str, None]]:
        """
        Send a voice message (MP3) to Telegram.
        :param voice_path: Path to the MP3/OGG audio file
        :return: (success, error_message)
        """
        try:
            if not os.path.exists(voice_path):
                return False, f"File not found: {voice_path}"

            url = f"{self.api_url}/sendVoice"
            with open(voice_path, "rb") as audio_file:
                payload = {
                    "chat_id": self.chat_id,
                    "caption": "🎙 The Data Drop — App Store Daily",
                }
                files = {"voice": ("episode.mp3", audio_file, "audio/mpeg")}
                response = requests.post(url, data=payload, files=files, timeout=60)

            if response.status_code == 200:
                return True, None
            return False, f"HTTP {response.status_code}: {response.text}"
        except Exception as e:
            return False, str(e)
