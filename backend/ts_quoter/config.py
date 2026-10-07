"""Configuración desde variables de entorno / .env. Nunca secretos en código."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Lector mínimo de .env (sin dependencia extra). No sobreescribe variables ya definidas."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    environment: str = field(default_factory=lambda: os.getenv("TSQ_ENV", "development"))
    database_url: str = field(default_factory=lambda: os.getenv("TSQ_DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'tsq.db'}"))
    storage_dir: Path = field(default_factory=lambda: Path(os.getenv("TSQ_STORAGE_DIR", str(ROOT / "data" / "projects"))))
    rules_path: Path = field(default_factory=lambda: Path(os.getenv("TSQ_RULES_PATH", str(ROOT / "rules" / "default_rules_v1.yaml"))))
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("TSQ_LOG_DIR", str(ROOT / "logs"))))
    # IA (sólo se usan a partir de la fase 4). Los nombres de modelo viven SOLO aquí.
    ai_provider: str = field(default_factory=lambda: os.getenv("TSQ_AI_PROVIDER", "none"))
    ai_text_model: str = field(default_factory=lambda: os.getenv("TSQ_AI_TEXT_MODEL", ""))
    ai_vision_model: str = field(default_factory=lambda: os.getenv("TSQ_AI_VISION_MODEL", ""))
    ai_fallback_model: str = field(default_factory=lambda: os.getenv("TSQ_AI_FALLBACK_MODEL", ""))
    ai_timeout_s: int = field(default_factory=lambda: int(os.getenv("TSQ_AI_TIMEOUT_S", "120")))
    allow_sample_data: bool = field(default_factory=lambda: os.getenv("TSQ_ALLOW_SAMPLE_DATA", "true").lower() == "true")

    # La API key NO se guarda en Settings para que nunca termine en un log o repr.
    @staticmethod
    def ai_api_key() -> str | None:
        return os.getenv("TSQ_AI_API_KEY")


settings = Settings()
