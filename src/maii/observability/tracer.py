"""Traçage des executions (section 5.4 du sujet).

Chaque ticket produit une trace identifiee par un `trace_id`. Chaque etape du
traitement produit un `Span` contenant son entree, sa sortie, sa latence, sa
consommation de jetons, son cout estime et son statut.

Double sortie :
  - `observability/traces.jsonl` : livrable brut, une ligne par span ;
  - `data/itsm.db` table `spans` : interrogeable par le tableau de bord.

Usage :
    tracer = Tracer.instance()
    with tracer.trace("tk-001") as trace:
        with trace.span("classification", entree=texte) as span:
            span.sortie = resultat
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from maii.models.schemas import Span

RACINE = Path(__file__).resolve().parents[3]
CHEMIN_JSONL = RACINE / "observability" / "traces.jsonl"
CHEMIN_DB = RACINE / "data" / "itsm.db"

_VERROU = threading.Lock()


def _serialisable(valeur: Any) -> Any:
    """Rend une valeur serialisable en JSON, sans jamais lever d'exception.

    Le traçage ne doit jamais faire echouer le traitement d'un ticket : en cas
    de valeur non serialisable, on retombe sur sa representation textuelle.
    """
    if valeur is None or isinstance(valeur, (str, int, float, bool)):
        return valeur
    if hasattr(valeur, "model_dump"):
        try:
            return valeur.model_dump(mode="json")
        except Exception:
            return str(valeur)
    if isinstance(valeur, dict):
        return {str(c): _serialisable(v) for c, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_serialisable(v) for v in valeur]
    return str(valeur)


class SpanEnCours:
    """Poignee permettant d'enrichir un span pendant son execution."""

    def __init__(self, span: Span) -> None:
        self._span = span
        self.sortie: Any = None
        self.tokens_entree: int = 0
        self.tokens_sortie: int = 0
        self.cout_usd: float = 0.0

    @property
    def span_id(self) -> str:
        return self._span.span_id


class TraceEnCours:
    """Trace d'un ticket : conteneur de spans partageant un `trace_id`."""

    def __init__(self, tracer: "Tracer", trace_id: str) -> None:
        self._tracer = tracer
        self.trace_id = trace_id
        self._pile: list[str] = []

    @contextmanager
    def span(self, nom: str, entree: Any = None) -> Iterator[SpanEnCours]:
        span = Span(
            trace_id=self.trace_id,
            span_id=uuid.uuid4().hex[:12],
            nom=nom,
            parent=self._pile[-1] if self._pile else None,
            entree=_serialisable(entree),
            horodatage=datetime.now(timezone.utc).isoformat(),
        )
        poignee = SpanEnCours(span)
        self._pile.append(span.span_id)
        debut = time.perf_counter()
        try:
            yield poignee
        except Exception as exc:
            span.statut = "erreur"
            span.erreur = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span.latence_ms = int((time.perf_counter() - debut) * 1000)
            span.sortie = _serialisable(poignee.sortie)
            span.tokens_entree = poignee.tokens_entree
            span.tokens_sortie = poignee.tokens_sortie
            span.cout_usd = poignee.cout_usd
            self._pile.pop()
            self._tracer.enregistrer(span)


class Tracer:
    """Ecrit les spans sur disque. Singleton, sur pour l'usage concurrent."""

    _instance: "Tracer | None" = None

    def __init__(self) -> None:
        CHEMIN_JSONL.parent.mkdir(parents=True, exist_ok=True)
        CHEMIN_DB.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def instance(cls) -> "Tracer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_db(self) -> None:
        with sqlite3.connect(CHEMIN_DB) as cx:
            cx.execute(
                """
                CREATE TABLE IF NOT EXISTS spans (
                    trace_id TEXT, span_id TEXT PRIMARY KEY, nom TEXT,
                    parent TEXT, entree TEXT, sortie TEXT, latence_ms INTEGER,
                    tokens_entree INTEGER, tokens_sortie INTEGER, cout_usd REAL,
                    statut TEXT, erreur TEXT, horodatage TEXT
                )
                """
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id)")

    @contextmanager
    def trace(self, trace_id: str | None = None) -> Iterator[TraceEnCours]:
        yield TraceEnCours(self, trace_id or f"tk-{uuid.uuid4().hex[:8]}")

    def enregistrer(self, span: Span) -> None:
        """Persiste un span. Une panne d'ecriture n'interrompt jamais le pipeline."""
        ligne = span.model_dump(mode="json")
        try:
            with _VERROU:
                with CHEMIN_JSONL.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                with sqlite3.connect(CHEMIN_DB) as cx:
                    cx.execute(
                        "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            span.trace_id, span.span_id, span.nom, span.parent,
                            json.dumps(ligne["entree"], ensure_ascii=False),
                            json.dumps(ligne["sortie"], ensure_ascii=False),
                            span.latence_ms, span.tokens_entree, span.tokens_sortie,
                            span.cout_usd, span.statut, span.erreur, span.horodatage,
                        ),
                    )
        except Exception:
            pass

    # ---------------- lecture, pour le tableau de bord ----------------

    def spans_de(self, trace_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(CHEMIN_DB) as cx:
            cx.row_factory = sqlite3.Row
            lignes = cx.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY horodatage", (trace_id,)
            ).fetchall()
        return [dict(l) for l in lignes]

    def metriques(self) -> dict[str, Any]:
        """Agregats affiches par l'onglet Observabilite."""
        with sqlite3.connect(CHEMIN_DB) as cx:
            cx.row_factory = sqlite3.Row
            lignes = [dict(l) for l in cx.execute("SELECT * FROM spans").fetchall()]
        if not lignes:
            return {"nb_traces": 0, "nb_spans": 0, "par_etape": {}, "cout_total": 0.0}

        par_etape: dict[str, dict[str, Any]] = {}
        for nom in {l["nom"] for l in lignes}:
            latences = sorted(l["latence_ms"] for l in lignes if l["nom"] == nom)
            concernes = [l for l in lignes if l["nom"] == nom]
            par_etape[nom] = {
                "appels": len(latences),
                "p50_ms": latences[len(latences) // 2],
                "p95_ms": latences[min(len(latences) - 1, int(len(latences) * 0.95))],
                "erreurs": sum(1 for l in concernes if l["statut"] == "erreur"),
            }
        return {
            "nb_traces": len({l["trace_id"] for l in lignes}),
            "nb_spans": len(lignes),
            "par_etape": par_etape,
            "cout_total": round(sum(l["cout_usd"] for l in lignes), 6),
            "tokens_total": sum(l["tokens_entree"] + l["tokens_sortie"] for l in lignes),
            "taux_erreur": round(
                sum(1 for l in lignes if l["statut"] == "erreur") / len(lignes), 4
            ),
        }
