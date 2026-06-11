"""
Main Module for FOMO Radio — The Data Drop
Pipeline: Report/Idea → Script Generation → TTS (multi-host) → MP3 → Telegram
"""
import os
import sys
import argparse
import asyncio
import edge_tts
import json
from datetime import datetime
from uuid import uuid4
import pytz
from pathlib import Path
from typing import List, Dict, Optional

# Load Hermes .env for API keys
_hermes_env = Path("/root/.hermes/.env")
if _hermes_env.exists():
    with open(_hermes_env) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

from utils.logger import custom_logger
from config import configuration as cf
from utils import json_loader, dir_checker
from data_collectors import ReportClient
from script_generators import ScriptClient, LLMClient
from consumers import TelegramConsumerClient

project_dir = os.path.dirname(os.path.abspath(__file__))
logger = custom_logger("FomoRadio", os.path.join(project_dir, cf.LOG_FOLDER))
logger.info("Fomo Radio started")
dir_checker(os.path.join(project_dir, cf.LOG_FOLDER))
dir_checker(os.path.join(project_dir, cf.MEDIA_FOLDER))


def initialize():
    """Load configurations"""
    show_config = json_loader(os.path.join(project_dir, "config", "show_config.json"))
    fomo_config = json_loader(os.path.join(project_dir, "config", "fomo_config.json"))
    persona_config = json_loader(os.path.join(project_dir, "config", "persona_config.json"))
    return show_config, fomo_config, persona_config


def load_idea_content(idea_path: str) -> List[str]:
    """Load a single idea.md file and return content strings."""
    content = []
    if os.path.exists(idea_path):
        with open(idea_path, "r", encoding="utf-8") as f:
            text = f.read()
        # Extract key sections
        for line in text.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                content.append(line)
    return content


async def generate_tts_two_host(script: str, hosts: List[Dict], output_path: str) -> bool:
    """
    Generate TTS for a two-host script.
    Parses [Host Name]: dialogue lines and generates per-speaker audio,
    then concatenates into a single MP3.
    """
    import re
    from pydub import AudioSegment

    try:
        # Parse script into speaker segments
        segments = []
        current_speaker = None
        current_text = []

        for line in script.split("\n"):
            line = line.strip()
            match = re.match(r"^\[(.+?)\]:\s*(.+)", line)
            if match:
                # Save previous segment
                if current_speaker and current_text:
                    segments.append((current_speaker, " ".join(current_text)))
                current_speaker = match.group(1).strip()
                current_text = [match.group(2).strip()]
            elif current_speaker and line:
                current_text.append(line)

        # Don't forget the last segment
        if current_speaker and current_text:
            segments.append((current_speaker, " ".join(current_text)))

        if not segments:
            # Fallback: treat entire script as single voice
            logger.warning("No speaker tags found, using single voice")
            voice_id = hosts[0].get("voice_id", "en-US-AriaNeural") if hosts else "en-US-AriaNeural"
            communicate = edge_tts.Communicate(script, voice_id)
            await communicate.save(output_path)
            return True

        # Build voice map from hosts
        voice_map = {}
        for host in hosts:
            name = host.get("host_name", "")
            voice = host.get("voice_id", "en-US-AriaNeural")
            voice_map[name] = voice

        # Default voice for unknown speakers
        default_voice = hosts[0].get("voice_id", "en-US-AriaNeural") if hosts else "en-US-AriaNeural"

        # Generate audio per segment
        combined = AudioSegment.empty()
        temp_files = []

        for i, (speaker, text) in enumerate(segments):
            voice_id = voice_map.get(speaker, default_voice)
            temp_path = os.path.join(project_dir, cf.MEDIA_FOLDER, f"_temp_segment_{i}.mp3")

            try:
                communicate = edge_tts.Communicate(text, voice_id)
                await communicate.save(temp_path)
                segment_audio = AudioSegment.from_mp3(temp_path)
                combined += segment_audio
                temp_files.append(temp_path)
            except Exception as e:
                logger.error("TTS failed for segment %d (%s): %s", i, speaker, e)
                continue

        # Export combined audio
        combined.export(output_path, format="mp3")

        # Cleanup temp files
        for tf in temp_files:
            try:
                os.remove(tf)
            except OSError:
                pass

        logger.info("Two-host audio saved to %s (%d segments)", output_path, len(segments))
        return True

    except Exception as e:
        logger.error("Two-host TTS generation failed: %s", str(e))
        return False


async def generate_tts_single(script: str, voice_id: str, output_path: str) -> bool:
    """Generate TTS audio from script using edge-tts (single host)."""
    try:
        communicate = edge_tts.Communicate(script, voice_id)
        await communicate.save(output_path)
        logger.info("Audio saved to %s", output_path)
        return True
    except Exception as e:
        logger.error("TTS generation failed: %s", str(e))
        return False


def main():
    """Main pipeline for FOMO Radio."""
    parser = argparse.ArgumentParser(description="FOMO Radio — Generate audio show")
    parser.add_argument("--report", type=str, help="Path to a specific report .md file")
    parser.add_argument("--report-dir", type=str, default=cf.REPORT_DIR,
                        help="Directory containing report files")
    parser.add_argument("--idea", type=str, help="Path to a specific idea.md file")
    parser.add_argument("--scope", choices=["idea", "daily"], default="daily",
                        help="Scope: single idea or daily summary (3 ideas)")
    parser.add_argument("--hosts", type=str, default="data,spock",
                        help="Comma-separated host names (e.g., data,spock)")
    parser.add_argument("--output", type=str, help="Custom output path for MP3")
    parser.add_argument("--no-telegram", action="store_true", help="Skip Telegram upload")
    args = parser.parse_args()

    show_config, fomo_config, persona_config = initialize()
    personas = persona_config.get("personas", [])

    # Resolve hosts
    host_names = [h.strip().lower() for h in args.hosts.split(",")]
    active_hosts = []
    for name in host_names:
        for p in personas:
            if p.get("host_name", "").lower() == name:
                active_hosts.append(p)
                break

    if not active_hosts:
        logger.error("No matching hosts found for: %s", args.hosts)
        sys.exit(1)

    logger.info("Active hosts: %s", [h.get("host_name") for h in active_hosts])

    # Step 1: Collect content based on scope
    logger.info("Collecting content (scope: %s)...", args.scope)

    if args.scope == "idea" and args.idea:
        # Single idea mode
        idea_content = load_idea_content(args.idea)
        contents = idea_content
        show_details = show_config.get("shows", [{}])[0]
    else:
        # Daily summary mode (default)
        report_client = ReportClient(
            report_path=args.report if args.report else "",
            report_dir=args.report_dir if not args.report else "",
        )
        raw_contents = report_client.process()
        contents = [item.get("content", "") for item in raw_contents if item.get("content")]
        show_details = show_config.get("shows", [{}])[0]

    if not contents:
        logger.error("No content found. Exiting.")
        sys.exit(1)

    logger.info("Collected %d content items", len(contents))

    # Step 2: Generate script
    logger.info("Generating radio script...")

    llm_config = fomo_config.get("llm", {})
    llm_config["provider"] = "openrouter"
    if not llm_config.get("model"):
        llm_config["model"] = "openrouter/owl-alpha"

    llm_api_key = os.environ.get("OPENROUTER_API_KEY", cf.LLM_API_KEY)
    if not llm_api_key:
        logger.error("No OpenRouter API key found.")
        sys.exit(1)

    llm_client_wrapper = LLMClient(llm_config, llm_api_key)
    llm_client, llm_interact = llm_client_wrapper.initialize_client()

    current_time = datetime.now(pytz.UTC).strftime("%I:%M %p UTC")

    # Build script client with two hosts
    script_client = ScriptClient(
        users=["Data", "Spock"][:len(active_hosts)],
        show_details=show_details,
        current_host=active_hosts[0],
        next_host=active_hosts[1].get("host_name", "") if len(active_hosts) > 1 else active_hosts[0].get("host_name", ""),
        second_host=active_hosts[1] if len(active_hosts) > 1 else None,
        contents=contents,
    )

    script_prompt = script_client.generate_prompt(["report"], current_time)
    logger.info("Sending prompt to LLM (%d chars)...", len(script_prompt))
    generated_script = llm_interact(llm_client, script_prompt)

    if not generated_script:
        logger.error("Script generation failed. Exiting.")
        sys.exit(1)

    cleaned_script = generated_script.replace("\n", " ")
    logger.info("Script generated (%d chars)", len(cleaned_script))

    # Save script
    timestamp = datetime.now(pytz.UTC).strftime("%Y%m%d_%H%M%S")
    script_path = os.path.join(project_dir, cf.MEDIA_FOLDER, f"script_{timestamp}.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(generated_script)  # Save original with speaker tags
    logger.info("Script saved to %s", script_path)

    # Step 3: Generate TTS
    logger.info("Generating TTS audio...")

    if args.output:
        mp3_path = args.output
    else:
        radio_name = show_config.get("radio_name", "DataDrop").replace(" ", "")
        show_id = show_details.get("show_id", 1)
        unique_id = uuid4().hex[:8]
        scope_tag = args.scope
        file_name = f"{radio_name}-{scope_tag}-{unique_id}-{timestamp}"
        mp3_path = os.path.join(project_dir, cf.MEDIA_FOLDER, f"{file_name}.mp3")

    if len(active_hosts) > 1:
        # Two-host mode
        success = asyncio.run(generate_tts_two_host(generated_script, active_hosts, mp3_path))
    else:
        # Single-host mode
        voice_id = active_hosts[0].get("voice_id", "en-US-AriaNeural")
        success = asyncio.run(generate_tts_single(cleaned_script, voice_id, mp3_path))

    if not success:
        logger.error("TTS generation failed. Exiting.")
        sys.exit(1)

    # Step 4: Deliver to Telegram
    if not args.no_telegram:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", cf.TELEGRAM_BOT_TOKEN)
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", cf.TELEGRAM_CHAT_ID)

        if bot_token and chat_id:
            logger.info("Sending to Telegram...")
            telegram_client = TelegramConsumerClient(bot_token, chat_id)
            is_sent, errors = telegram_client.send_voice(mp3_path)
            if is_sent:
                logger.info("Voice message sent to Telegram!")
            else:
                logger.error("Telegram delivery failed: %s", errors)
        else:
            logger.warning("Telegram not configured. Skipping.")
    else:
        logger.info("Skipping Telegram. MP3 saved to %s", mp3_path)

    logger.info("FOMO Radio episode complete!")
    print("\nEpisode generated successfully!")
    print(f"   Script: {script_path}")
    print(f"   Audio:  {mp3_path}")
    print(f"   Hosts:  {', '.join(h.get('host_name') for h in active_hosts)}")


if __name__ == "__main__":
    main()
