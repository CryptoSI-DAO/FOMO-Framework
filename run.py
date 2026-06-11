"""
Main Module for FOMO Radio — The Data Drop
Simplified pipeline: Report → Script Generation → TTS → MP3 → Telegram
"""
import os
import sys
import argparse
import asyncio
import edge_tts
from datetime import datetime
from uuid import uuid4
import pytz
from pathlib import Path

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

# Loading Folders
project_dir = os.path.dirname(os.path.abspath(__file__))

# Logger Module
logger = custom_logger("FomoRadio", os.path.join(project_dir, cf.LOG_FOLDER))
logger.info("Fomo Radio started")

# Create Logs and Media Directory
dir_checker(os.path.join(project_dir, cf.LOG_FOLDER))
dir_checker(os.path.join(project_dir, cf.MEDIA_FOLDER))


def initialize():
    """Load configurations"""
    show_config = json_loader(os.path.join(project_dir, "config", "show_config.json"))
    logger.info("Show configurations loaded")
    fomo_config = json_loader(os.path.join(project_dir, "config", "fomo_config.json"))
    logger.info("Fomo Radio configurations loaded")
    persona_config = json_loader(os.path.join(project_dir, "config", "persona_config.json"))
    logger.info("Persona configurations loaded")
    return show_config, fomo_config, persona_config


async def generate_tts(script: str, voice_id: str, output_path: str) -> bool:
    """Generate TTS audio from script using edge-tts."""
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
    parser = argparse.ArgumentParser(description="FOMO Radio — Generate audio show from report")
    parser.add_argument("--report", type=str, help="Path to a specific report .md file")
    parser.add_argument("--report-dir", type=str, default=cf.REPORT_DIR,
                        help="Directory containing report files")
    parser.add_argument("--output", type=str, help="Custom output path for MP3")
    parser.add_argument("--no-telegram", action="store_true", help="Skip Telegram upload")
    args = parser.parse_args()

    # Initialize configs
    show_config, fomo_config, persona_config = initialize()

    # Get the report path
    report_path = args.report
    report_dir = args.report_dir

    if not report_path and not report_dir:
        logger.error("Either --report or --report-dir must be specified")
        sys.exit(1)

    # Step 1: Collect data from report
    logger.info("Starting data collection from report...")
    report_client = ReportClient(
        report_path=report_path if report_path else "",
        report_dir=report_dir if not report_path else "",
    )
    contents = report_client.process()
    logger.info("Collected %d content items from report", len(contents))

    if not contents:
        logger.error("No content found in report. Exiting.")
        sys.exit(1)

    # Step 2: Generate script
    logger.info("Generating radio script...")
    personas = persona_config.get("personas", [])
    if not personas:
        logger.error("No personas found in config. Exiting.")
        sys.exit(1)

    current_persona = personas[0]
    next_persona_name = personas[0].get("host_name", "Data")

    # Override LLM config to use OpenRouter from Hermes env
    llm_config = fomo_config.get("llm", {})
    llm_config["provider"] = "openrouter"
    if not llm_config.get("model"):
        llm_config["model"] = "openrouter/owl-alpha"

    llm_api_key = os.environ.get("OPENROUTER_API_KEY", cf.LLM_API_KEY)
    if not llm_api_key:
        logger.error("No OpenRouter API key found. Set OPENROUTER_API_KEY env var.")
        sys.exit(1)

    llm_client_wrapper = LLMClient(llm_config, llm_api_key)
    llm_client, llm_interact = llm_client_wrapper.initialize_client()

    show_details = show_config.get("shows", [{}])[0]
    current_time = datetime.now(pytz.UTC).strftime("%I:%M %p UTC")

    # Format content for the prompt
    content_lines = []
    for item in contents:
        c = item.get("content", "")
        if c:
            content_lines.append(f"- {c}")
    formatted_content = "\n".join(content_lines)

    # Create script client with direct content (no memory)
    class SimpleScriptClient(ScriptClient):
        """Override to work without memory system."""
        def extract_memories(self, agent):
            return [item.get("content", "") for item in contents]

    script_client = SimpleScriptClient(
        users=["Data"],
        show_details=show_details,
        current_host=current_persona,
        next_host=next_persona_name,
    )

    script_prompt = script_client.generate_prompt(["report"], current_time)
    logger.info("Sending prompt to LLM (%d chars)...", len(script_prompt))
    generated_script = llm_interact(llm_client, script_prompt)

    if not generated_script:
        logger.error("Script generation failed. Exiting.")
        sys.exit(1)

    cleaned_script = generated_script.replace("\n", " ")
    logger.info("Script generated (%d chars)", len(cleaned_script))

    # Save script to file for reference
    timestamp = datetime.now(pytz.UTC).strftime("%Y%m%d_%H%M%S")
    script_path = os.path.join(project_dir, cf.MEDIA_FOLDER, f"script_{timestamp}.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(cleaned_script)
    logger.info("Script saved to %s", script_path)

    # Step 3: Generate TTS audio
    logger.info("Generating TTS audio...")
    voice_id = current_persona.get("voice_id", "en-US-AriaNeural")

    if args.output:
        mp3_path = args.output
    else:
        radio_name = show_config.get("radio_name", "DataDrop").replace(" ", "")
        show_id = show_details.get("show_id", 1)
        unique_id = uuid4().hex[:8]
        file_name = f"{radio_name}-{show_id}-{unique_id}-{timestamp}"
        mp3_path = os.path.join(project_dir, cf.MEDIA_FOLDER, f"{file_name}.mp3")

    success = asyncio.run(generate_tts(cleaned_script, voice_id, mp3_path))
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
                logger.info("Voice message sent to Telegram successfully!")
            else:
                logger.error("Telegram delivery failed: %s", errors)
        else:
            logger.warning("Telegram credentials not configured. Skipping.")
            logger.info("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars.")
    else:
        logger.info("Skipping Telegram. MP3 saved to %s", mp3_path)

    logger.info("FOMO Radio episode complete!")
    print("\nEpisode generated successfully!")
    print(f"   Script: {script_path}")
    print(f"   Audio:  {mp3_path}")


if __name__ == "__main__":
    main()
