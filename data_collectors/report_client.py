"""
Report Client for FOMO Radio
Reads daily App Store research report files and formats them for script generation.
"""
import os
import glob
from typing import Tuple, List, Dict
from datetime import datetime, timezone
from data_collectors.collector import BaseCollector
from data_collectors.granule import Granule


class ReportClient(BaseCollector):
    """
    Collector that reads daily App Store research report files
    and converts them into Granule format for the script generator.
    """

    source: str = "report"

    def __init__(self, report_path: str = "", report_dir: str = ""):
        """
        Initialize with either a specific report file path or a directory
        containing daily report files.
        :param report_path: Path to a specific report .md file
        :param report_dir: Directory containing report subdirectories (e.g. /workspace/app-ideas/ideas/)
        """
        super().__init__()
        self.report_path = report_path
        self.report_dir = report_dir

    def _find_latest_report(self) -> str:
        """Find the most recent daily-summary.md in the report directory."""
        pattern = os.path.join(self.report_dir, "*", "daily-summary.md")
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"No daily-summary.md files found in {self.report_dir}")
        # Sort by modification time, newest first
        files.sort(key=os.path.getmtime, reverse=True)
        return files[0]

    def _parse_report(self, file_path: str) -> List[Dict]:
        """
        Parse a daily-summary.md file into structured content blocks.
        Returns a list of dicts with 'title', 'content', 'score', 'category' keys.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        ideas = []
        trends = []
        rejected = []
        current_section = None
        current_idea = None

        for line in content.split("\n"):
            line = line.strip()

            # Detect sections
            if line.startswith("## Top 3 App Ideas"):
                current_section = "top_ideas"
                continue
            elif line.startswith("## All Ideas Scored"):
                current_section = "scored"
                continue
            elif line.startswith("## Rejected"):
                current_section = "rejected"
                continue
            elif line.startswith("## Trends Watched"):
                current_section = "trends"
                continue
            elif line.startswith("## Sources Checked"):
                current_section = "sources"
                continue
            elif line.startswith("## Archive Notes"):
                current_section = "archive"
                continue

            # Parse top ideas
            if current_section == "top_ideas":
                if line.startswith("### ") and ("#" in line or "Score" in line):
                    # Save previous idea
                    if current_idea:
                        ideas.append(current_idea)
                    # Start new idea
                    title = line.replace("### ", "").strip()
                    # Clean up ranking prefix like "🥇 #1: "
                    for prefix in ["🥇 ", "🥈 ", "🥉 "]:
                        title = title.replace(prefix, "")
                    if "# " in title:
                        title = title.split(": ", 1)[-1] if ": " in title else title
                    current_idea = {
                        "title": title,
                        "pitch": "",
                        "why": "",
                        "build_time": "",
                        "pricing": "",
                        "score": "",
                        "content_blocks": [],
                    }
                elif current_idea is not None:
                    if line.startswith("- **Pitch**:"):
                        current_idea["pitch"] = line.split(":", 1)[1].strip()
                    elif line.startswith("- **Why**:"):
                        current_idea["why"] = line.split(":", 1)[1].strip()
                    elif line.startswith("- **Build Time**:"):
                        current_idea["build_time"] = line.split(":", 1)[1].strip()
                    elif line.startswith("- **Pricing**:"):
                        current_idea["pricing"] = line.split(":", 1)[1].strip()
                    elif "Score:" in line:
                        # Extract score like "Score: 8.2/10"
                        try:
                            score_part = line.split("Score:")[-1].strip()
                            current_idea["score"] = score_part
                        except (IndexError, ValueError):
                            pass
                    elif line.startswith("- "):
                        current_idea["content_blocks"].append(line[2:])

        # Don't forget the last idea
        if current_idea:
            ideas.append(current_idea)

        # Parse trends
        if current_section == "trends":
            if line.startswith("- **"):
                trend_text = line.replace("- **", "").replace("**", "")
                trends.append(trend_text)

        # Parse rejected
        if current_section == "rejected":
            if line.startswith("- "):
                rejected_text = line[2:]
                if "REJECTED" in rejected_text:
                    rejected.append(rejected_text)

        return {
            "ideas": ideas,
            "trends": trends,
            "rejected": rejected,
            "file_path": file_path,
            "date": os.path.basename(os.path.dirname(file_path)),
        }

    def _format_for_granule(self, parsed: Dict) -> List[Dict]:
        """
        Convert parsed report data into Granule-compatible dicts.
        Each idea becomes a content item with metadata.
        """
        granules = []
        timestamp = datetime.now(timezone.utc).isoformat()

        for idea in parsed["ideas"]:
            # Build a rich content string for each idea
            content_parts = [f"App idea: {idea['title']}"]
            if idea["pitch"]:
                content_parts.append(f"Description: {idea['pitch']}")
            if idea["why"]:
                content_parts.append(f"Why it matters: {idea['why']}")
            if idea["build_time"]:
                content_parts.append(f"Build time: {idea['build_time']}")
            if idea["pricing"]:
                content_parts.append(f"Pricing: {idea['pricing']}")
            if idea["score"]:
                content_parts.append(f"Score: {idea['score']}")

            content = ". ".join(content_parts)

            granule = Granule(
                source=self.source,
                timestamp=timestamp,
                content=content,
                user="Data",
                metadata={
                    "idea_title": idea["title"],
                    "score": idea["score"],
                    "category": "app_idea",
                    "report_date": parsed["date"],
                },
            )
            granules.append(granule.to_dict())

        # Add trends as separate granules
        for trend in parsed["trends"]:
            granule = Granule(
                source=self.source,
                timestamp=timestamp,
                content=f"Trending: {trend}",
                user="Data",
                metadata={
                    "category": "trend",
                    "report_date": parsed["date"],
                },
            )
            granules.append(granule.to_dict())

        return granules

    def fetch(self) -> Tuple[List[Dict], str, str, str]:
        """
        Fetch report data. Returns (records, timestamp_key, content_key, user_key)
        compatible with BaseCollector.process().
        """
        if self.report_path:
            report_file = self.report_path
        elif self.report_dir:
            report_file = self._find_latest_report()
        else:
            raise ValueError("Either report_path or report_dir must be provided")

        parsed = self._parse_report(report_file)
        granules = self._format_for_granule(parsed)

        # Return in the format BaseCollector.process() expects
        return (granules, "timestamp", "content", "user")

    def process(self) -> List[Dict]:
        """
        Override process to return granules directly (already formatted).
        """
        records, _, _, _ = self.fetch()
        return records
