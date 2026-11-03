"""Launch the Proctor API + dashboard.  Run:  python -m proctor.server"""

import logging

import uvicorn

from . import config, db


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    db.init()
    print(f"\n  Proctor dashboard → http://{config.API_HOST}:{config.API_PORT}")
    print(f"  Engine mode: {config.ENGINE_MODE}  (LLM {'ON' if config.llm_enabled() else 'OFF'})\n")
    uvicorn.run("proctor.api:app", host=config.API_HOST, port=config.API_PORT, log_level="info")


if __name__ == "__main__":
    main()
