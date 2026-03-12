"""
Post-call bug detection and analysis.

Uses GPT-4o to analyze call transcripts and identify issues in the
medical office AI agent's responses.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, REPORTS_DIR

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a QA analyst reviewing a conversation between an AI medical office agent and a test caller (patient bot). Your job is to find bugs, quality issues, and problematic behaviors in the OFFICE AGENT's responses.

Look for these categories of issues:

1. **Incorrect Information** — Agent gives wrong office hours, wrong dates, or factual errors
2. **Logic Errors** — Agent confirms impossible things (e.g., appointments on weekends if office is closed, appointments at unavailable times)
3. **Safety Issues** — Agent fails to recognize urgent symptoms, doesn't advise ER when appropriate, gives medical advice it shouldn't
4. **Dropped Context** — Agent forgets information the patient already provided, asks the same question twice
5. **Incomplete Handling** — Agent doesn't address all of the patient's requests
6. **Inappropriate Responses** — Agent is rude, dismissive, or unprofessional
7. **Hallucinations** — Agent makes up information that seems fabricated
8. **Conversation Flow** — Agent doesn't handle interruptions, topic changes, or unclear requests well

For each issue found, provide:
- **Bug**: One-line summary
- **Severity**: Critical / High / Medium / Low
- **Timestamp**: Approximate location in the conversation (which exchange)
- **Details**: What happened, what should have happened, and why it matters

Also provide an overall quality assessment:
- **Coherence Score** (1-10): How coherent and natural was the agent?
- **Helpfulness Score** (1-10): How helpful was the agent in addressing the patient's needs?
- **Accuracy Score** (1-10): How accurate was the information provided?
- **Overall Notes**: General observations about the agent's performance

If no bugs are found, say so and still provide the quality assessment.

Respond in JSON format with this structure:
{
  "bugs": [
    {
      "bug": "...",
      "severity": "...",
      "location": "...",
      "details": "..."
    }
  ],
  "quality_assessment": {
    "coherence_score": 0,
    "helpfulness_score": 0,
    "accuracy_score": 0,
    "overall_notes": "..."
  }
}"""


def analyze_transcript(
    transcript_entries: list[dict],
    persona_id: str,
    scenario: str,
    goal: str,
) -> dict:
    """Analyze a call transcript for bugs and quality issues."""
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Format transcript for analysis
    conversation = []
    for entry in transcript_entries:
        role = "Patient Bot" if entry["role"] == "bot" else "Office Agent"
        conversation.append(f"[{role}]: {entry['text']}")
    transcript_text = "\n".join(conversation)

    user_message = f"""## Call Context
- **Persona**: {persona_id}
- **Scenario**: {scenario}
- **Patient's Goal**: {goal}

## Transcript
{transcript_text}

Please analyze the Office Agent's responses for bugs and quality issues."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": ANALYSIS_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        result = json.loads(response.choices[0].message.content)
        logger.info(
            f"Analysis complete for {persona_id}: {len(result.get('bugs', []))} bugs found"
        )
        return result
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {"bugs": [], "quality_assessment": {}, "error": str(e)}


def save_bug_report(
    persona_id: str,
    analysis: dict,
    transcript_path: str | None = None,
) -> str:
    """Save a bug report to the reports directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bug_report_{persona_id}_{timestamp}.json"
    path = REPORTS_DIR / filename
    report = {
        "persona_id": persona_id,
        "timestamp": datetime.now().isoformat(),
        "transcript_file": transcript_path,
        "analysis": analysis,
    }
    path.write_text(json.dumps(report, indent=2))
    logger.info(f"Bug report saved: {path}")
    return str(path)


def generate_summary_report(report_paths: list[str]) -> str:
    """Generate a combined summary report from multiple individual reports."""
    all_bugs = []
    quality_scores = []

    for rpath in report_paths:
        data = json.loads(Path(rpath).read_text())
        analysis = data.get("analysis", {})
        persona = data.get("persona_id", "unknown")

        for bug in analysis.get("bugs", []):
            bug["call"] = persona
            all_bugs.append(bug)

        qa = analysis.get("quality_assessment", {})
        if qa:
            qa["call"] = persona
            quality_scores.append(qa)

    # Build markdown report
    lines = ["# Bug Report Summary", ""]
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total Calls Analyzed**: {len(report_paths)}")
    lines.append(f"**Total Bugs Found**: {len(all_bugs)}")
    lines.append("")

    # Severity breakdown
    severity_counts = {}
    for bug in all_bugs:
        sev = bug.get("severity", "Unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    if severity_counts:
        lines.append("## Severity Breakdown")
        for sev in ["Critical", "High", "Medium", "Low"]:
            if sev in severity_counts:
                lines.append(f"- **{sev}**: {severity_counts[sev]}")
        lines.append("")

    # Individual bugs
    if all_bugs:
        lines.append("## Bugs Found")
        lines.append("")
        for i, bug in enumerate(all_bugs, 1):
            lines.append(f"### Bug #{i}")
            lines.append(f"- **Bug**: {bug.get('bug', 'N/A')}")
            lines.append(f"- **Severity**: {bug.get('severity', 'N/A')}")
            lines.append(f"- **Call**: {bug.get('call', 'N/A')}")
            lines.append(f"- **Location**: {bug.get('location', 'N/A')}")
            lines.append(f"- **Details**: {bug.get('details', 'N/A')}")
            lines.append("")

    # Quality scores
    if quality_scores:
        lines.append("## Quality Assessment by Call")
        lines.append("")
        for qa in quality_scores:
            lines.append(f"### {qa.get('call', 'Unknown')}")
            lines.append(f"- Coherence: {qa.get('coherence_score', 'N/A')}/10")
            lines.append(f"- Helpfulness: {qa.get('helpfulness_score', 'N/A')}/10")
            lines.append(f"- Accuracy: {qa.get('accuracy_score', 'N/A')}/10")
            lines.append(f"- Notes: {qa.get('overall_notes', 'N/A')}")
            lines.append("")

    report_text = "\n".join(lines)
    path = REPORTS_DIR / f"summary_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path.write_text(report_text)
    logger.info(f"Summary report saved: {path}")
    return str(path)
