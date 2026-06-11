"""
Generates Script for the Show
"""
from typing import List, Dict, Optional
from config.prompt import SCRIPT_GENERATION_PROMPT, CONTENT_GENERATION_PROMPT


class ScriptClient:
    """
    Script Generator for the show.
    Supports single-host and two-host (Data + Spock) formats.
    """

    users: List[str] = None
    current_host: Dict = None
    next_host: str = None
    show_details: Dict = None
    second_host: Optional[Dict] = None
    contents: List[str] = None

    def __init__(
        self,
        users: List[str],
        show_details: Dict,
        current_host: Dict,
        next_host: str,
        second_host: Dict = None,
        contents: List[str] = None,
    ):
        self.users = users
        self.current_host = current_host
        self.next_host = next_host
        self.show_details = show_details
        self.second_host = second_host
        self.contents = contents or []

    def extract_memories(self, agent: str) -> List:
        """Return pre-loaded content directly (no memory system)."""
        return self.contents

    def generate_prompt(self, agents: List, current_time: str) -> str:
        """
        Generate the prompt for creating the show script.
        Supports two-host format when second_host is provided.
        """
        contents = self.contents

        # Build host persona strings
        host_1 = self._format_persona(self.current_host)
        host_2 = ""
        if self.second_host:
            host_2 = self._format_persona(self.second_host)

        show_name = self.show_details.get("name", "App Store Daily")
        show_motive = self.show_details.get("description", "")
        radio_name = self.show_details.get("aired_on", "The Data Drop")

        return SCRIPT_GENERATION_PROMPT.format(
            show_name=show_name,
            show_motive=show_motive,
            radio_name=radio_name,
            host_1=host_1,
            host_2=host_2,
            host=self.current_host,
            host_name=self.current_host.get("host_name", "Data"),
            current_utc_time=current_time,
            alternate_host_name=self.next_host,
            formatted_content=contents,
        )

    def generate_content(self, agents: List) -> str:
        """Generate social media content for the show."""
        contents = self.contents
        return CONTENT_GENERATION_PROMPT.format(
            show_name=self.show_details.get("name", "App Store Daily"),
            host_name=self.current_host.get("host_name", "Data"),
            formatted_content=contents,
        )

    def _format_persona(self, host: Dict) -> str:
        """Format a host persona dict into a readable string for the prompt."""
        if not host:
            return ""
        persona = host.get("persona", {})
        name = host.get("host_name", "Host")
        tone = persona.get("tone", "")
        style = persona.get("style", "")
        traits = ", ".join(persona.get("traits", []))
        catchphrases = ", ".join(persona.get("catchphrases", []))
        return f"{name}: {tone} tone, {style} style. Traits: {traits}. Catchphrases: {catchphrases}"
