#!/usr/bin/env python3
"""
Pretty Good AI — Voice Bot Test Runner

Main entry point. Starts the webhook server, places calls with different
patient personas, records everything, and generates bug reports.

Usage:
    # Run all personas:
    python main.py --all

    # Run a specific persona:
    python main.py --persona scheduling_simple

    # List available personas:
    python main.py --list

    # Run a batch of specific personas:
    python main.py --persona scheduling_simple weekend_appointment urgent_care
"""

import argparse
import asyncio
import logging
import signal
import sys
import threading
import time

import uvicorn

from config import SERVER_PORT, PUBLIC_URL
from personas_loader import list_personas, load_persona
from caller import place_call, wait_for_call_completion, convert_ulaw_to_mp3, download_twilio_recording
from bug_detector import analyze_transcript, save_bug_report, generate_summary_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def start_server_thread():
    """Start the FastAPI server in a background thread."""
    config = uvicorn.Config(
        "server:app",
        host="0.0.0.0",
        port=SERVER_PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    logger.info(f"Webhook server started on port {SERVER_PORT}")
    time.sleep(2)  # Let it start up
    return server


def validate_config():
    """Check that required env vars are set."""
    from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, OPENAI_API_KEY

    missing = []
    if not TWILIO_ACCOUNT_SID:
        missing.append("TWILIO_ACCOUNT_SID")
    if not TWILIO_AUTH_TOKEN:
        missing.append("TWILIO_AUTH_TOKEN")
    if not TWILIO_PHONE_NUMBER:
        missing.append("TWILIO_PHONE_NUMBER")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not PUBLIC_URL:
        missing.append("PUBLIC_URL")

    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)


def run_persona(persona_id: str, delay_between: int = 5) -> dict:
    """Execute a single call with the given persona. Returns the result summary."""
    persona = load_persona(persona_id)
    logger.info(f"\n{'='*60}")
    logger.info(f"STARTING CALL: {persona.scenario}")
    logger.info(f"Persona: {persona.name} ({persona.id})")
    logger.info(f"Goal: {persona.goal}")
    logger.info(f"{'='*60}")

    # Place the call
    call_sid = place_call(persona.id, persona.system_prompt)

    # Wait for it to complete
    session = wait_for_call_completion(call_sid, timeout=300)

    result = {
        "persona_id": persona.id,
        "scenario": persona.scenario,
        "call_sid": call_sid,
        "status": session.get("status", "unknown"),
        "transcript_path": session.get("transcript_path"),
        "audio_path": session.get("audio_path"),
        "mp3_path": None,
        "twilio_mp3_path": None,
        "report_path": None,
    }

    # Convert recording to MP3
    if session.get("audio_path"):
        mp3 = convert_ulaw_to_mp3(session["audio_path"])
        result["mp3_path"] = mp3

    # Try to download Twilio's recording as backup
    time.sleep(5)  # Give Twilio a moment to process the recording
    twilio_mp3 = download_twilio_recording(call_sid)
    result["twilio_mp3_path"] = twilio_mp3

    # Analyze transcript for bugs
    transcript = session.get("transcript", [])
    if transcript:
        logger.info("Analyzing transcript for bugs...")
        analysis = analyze_transcript(
            transcript,
            persona.id,
            persona.scenario,
            persona.goal,
        )
        report_path = save_bug_report(
            persona.id,
            analysis,
            session.get("transcript_path"),
        )
        result["report_path"] = report_path

        # Print bug summary
        bugs = analysis.get("bugs", [])
        if bugs:
            logger.info(f"Found {len(bugs)} potential issue(s):")
            for bug in bugs:
                logger.info(f"  [{bug['severity']}] {bug['bug']}")
        else:
            logger.info("No bugs detected in this call.")

        qa = analysis.get("quality_assessment", {})
        if qa:
            logger.info(
                f"Quality: coherence={qa.get('coherence_score')}/10 "
                f"helpful={qa.get('helpfulness_score')}/10 "
                f"accuracy={qa.get('accuracy_score')}/10"
            )
    else:
        logger.warning("No transcript captured — skipping analysis")

    logger.info(f"Call {persona.id} finished.\n")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Pretty Good AI Voice Bot — Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --list                           # Show all personas
  python main.py --persona scheduling_simple      # Run one persona
  python main.py --persona scheduling_simple weekend_appointment  # Run several
  python main.py --all                            # Run all personas
  python main.py --all --delay 30                 # Run all with 30s gap between calls
        """,
    )
    parser.add_argument("--list", action="store_true", help="List available personas and exit")
    parser.add_argument("--persona", nargs="+", help="Persona ID(s) to run")
    parser.add_argument("--all", action="store_true", help="Run all personas")
    parser.add_argument("--delay", type=int, default=15, help="Seconds between calls (default: 15)")
    parser.add_argument("--no-analysis", action="store_true", help="Skip post-call bug analysis")

    args = parser.parse_args()

    # List mode
    if args.list:
        personas = list_personas()
        print(f"\nAvailable Personas ({len(personas)}):\n")
        for p in personas:
            print(f"  {p.id:<25} {p.scenario}")
            print(f"  {'':25} -> {p.name}, {p.description[:60]}...")
            print()
        return

    # Validate env
    validate_config()

    # Determine which personas to run
    if args.all:
        persona_ids = [p.id for p in list_personas()]
    elif args.persona:
        persona_ids = args.persona
    else:
        parser.print_help()
        return

    logger.info(f"Will run {len(persona_ids)} call(s): {', '.join(persona_ids)}")
    logger.info(f"Public URL: {PUBLIC_URL}")

    # Start webhook server
    start_server_thread()

    # Run calls sequentially
    results = []
    report_paths = []

    for i, pid in enumerate(persona_ids):
        try:
            result = run_persona(pid)
            results.append(result)
            if result.get("report_path"):
                report_paths.append(result["report_path"])
        except Exception as e:
            logger.error(f"Failed to run persona {pid}: {e}")
            results.append({"persona_id": pid, "status": "error", "error": str(e)})

        # Delay between calls (except after the last one)
        if i < len(persona_ids) - 1:
            logger.info(f"Waiting {args.delay}s before next call...")
            time.sleep(args.delay)

    # Generate summary report
    if report_paths:
        summary_path = generate_summary_report(report_paths)
        logger.info(f"\nSummary report: {summary_path}")

    # Print final summary
    print(f"\n{'='*60}")
    print("RUN COMPLETE")
    print(f"{'='*60}")
    print(f"Total calls: {len(results)}")
    print(f"Successful:  {sum(1 for r in results if r.get('status') == 'completed')}")
    print(f"Failed:      {sum(1 for r in results if r.get('status') != 'completed')}")
    if report_paths:
        print(f"Bug reports:  {len(report_paths)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
