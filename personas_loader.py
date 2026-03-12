"""Loads patient persona definitions from JSON files."""

import json
from pathlib import Path
from dataclasses import dataclass
from config import PERSONAS_DIR


@dataclass
class Persona:
    id: str
    name: str
    scenario: str
    description: str
    system_prompt: str
    goal: str
    edge_cases_to_probe: list[str]
    expected_duration_seconds: int


def load_persona(persona_id: str) -> Persona:
    """Load a single persona by its ID (filename without .json)."""
    path = PERSONAS_DIR / f"{persona_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Persona not found: {path}")
    data = json.loads(path.read_text())
    return Persona(**data)


def list_personas() -> list[Persona]:
    """Load all available personas."""
    personas = []
    for path in sorted(PERSONAS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        personas.append(Persona(**data))
    return personas
