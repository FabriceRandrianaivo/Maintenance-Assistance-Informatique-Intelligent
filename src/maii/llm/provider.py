"""Acces aux modeles de langage, avec bascule automatique.

Le reseau d'une salle d'examen est le premier point de panne du prototype. On
definit donc une chaine de secours a quatre niveaux :

    1. Groq        - llama-3.3-70b-versatile  (gratuit, faible latence, mode JSON)
    2. Gemini      - gemini-2.0-flash         (secours reseau)
    3. Ollama      - qwen2.5:7b-instruct      (secours local, hors ligne)
    4. indisponible                           (le systeme bascule en mode regles)

Le quatrieme niveau n'est pas une panne : le pipeline reste fonctionnel sans
aucun modele de langage, en s'appuyant sur les regles, TF-IDF et BM25. Les deux
modes sont mesures separement dans le rapport d'evaluation.

L'acces se fait en HTTP direct plutot que par les SDK des fournisseurs : une
seule implementation a maintenir, aucune dependance supplementaire, et aucun
risque de rupture d'API un jour d'examen.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

# Tarifs indicatifs en dollars par million de jetons, pour l'estimation de cout.
TARIFS = {
    "groq": (0.0, 0.0),
    "gemini": (0.0, 0.0),
    "ollama": (0.0, 0.0),
}

DELAI_MAX_S = 25


@dataclass
class ReponseLLM:
    """Reponse d'un modele, enrichie des metriques necessaires au traçage."""

    texte: str
    provider: str
    modele: str
    tokens_entree: int = 0
    tokens_sortie: int = 0
    cout_usd: float = 0.0
    latence_ms: int = 0
    erreur: str | None = None

    @property
    def ok(self) -> bool:
        return self.erreur is None and bool(self.texte)


@dataclass
class Provider:
    nom: str
    modele: str
    disponible: bool = False
    motif: str = ""


class LLMClient:
    """Client unifie, avec bascule automatique sur le premier provider valide."""

    def __init__(self) -> None:
        self.providers: list[Provider] = []
        self._detecter()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detecter(self) -> None:
        cle_groq = os.getenv("GROQ_API_KEY", "").strip()
        self.providers.append(
            Provider(
                "groq",
                os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                disponible=bool(cle_groq),
                motif="" if cle_groq else "GROQ_API_KEY absente",
            )
        )

        cle_gemini = os.getenv("GEMINI_API_KEY", "").strip()
        self.providers.append(
            Provider(
                "gemini",
                os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
                disponible=bool(cle_gemini),
                motif="" if cle_gemini else "GEMINI_API_KEY absente",
            )
        )

        hote_ollama = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        dispo = False
        try:
            dispo = requests.get(f"{hote_ollama}/api/tags", timeout=1.5).ok
        except Exception:
            dispo = False
        self.providers.append(
            Provider(
                "ollama",
                os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
                disponible=dispo,
                motif="" if dispo else "serveur local injoignable",
            )
        )

    @property
    def actif(self) -> Provider | None:
        """Premier provider disponible dans l'ordre de preference."""
        return next((p for p in self.providers if p.disponible), None)

    @property
    def mode(self) -> str:
        p = self.actif
        return f"{p.nom}:{p.modele}" if p else "regles_seules"

    @property
    def disponible(self) -> bool:
        return self.actif is not None

    def diagnostic(self) -> list[dict[str, Any]]:
        """Etat de chaque provider, affiche dans l'onglet Observabilite."""
        return [
            {"provider": p.nom, "modele": p.modele, "disponible": p.disponible,
             "motif": p.motif}
            for p in self.providers
        ]

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generer(
        self,
        systeme: str,
        utilisateur: str,
        json_attendu: bool = False,
        temperature: float = 0.0,
    ) -> ReponseLLM:
        """Interroge les providers dans l'ordre, jusqu'a obtenir une reponse.

        Un echec (cle invalide, quota, reseau) fait passer au suivant. Si tous
        echouent, la reponse porte une erreur et l'appelant bascule en mode
        deterministe.
        """
        derniere_erreur = "aucun provider disponible"
        for p in self.providers:
            if not p.disponible:
                continue
            debut = time.perf_counter()
            try:
                reponse = self._appeler(p, systeme, utilisateur, json_attendu, temperature)
                reponse.latence_ms = int((time.perf_counter() - debut) * 1000)
                if reponse.ok:
                    return reponse
                derniere_erreur = reponse.erreur or "reponse vide"
            except Exception as exc:
                derniere_erreur = f"{type(exc).__name__}: {exc}"
            # Le provider vient d'echouer : on ne le retente pas sur ce ticket.
            p.disponible = False
            p.motif = derniere_erreur

        return ReponseLLM(texte="", provider="aucun", modele="", erreur=derniere_erreur)

    def _appeler(
        self, p: Provider, systeme: str, utilisateur: str,
        json_attendu: bool, temperature: float,
    ) -> ReponseLLM:
        if p.nom == "groq":
            return self._groq(p, systeme, utilisateur, json_attendu, temperature)
        if p.nom == "gemini":
            return self._gemini(p, systeme, utilisateur, json_attendu, temperature)
        return self._ollama(p, systeme, utilisateur, json_attendu, temperature)

    def _groq(self, p, systeme, utilisateur, json_attendu, temperature) -> ReponseLLM:
        charge: dict[str, Any] = {
            "model": p.modele,
            "messages": [
                {"role": "system", "content": systeme},
                {"role": "user", "content": utilisateur},
            ],
            "temperature": temperature,
        }
        if json_attendu:
            charge["response_format"] = {"type": "json_object"}

        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
            json=charge,
            timeout=DELAI_MAX_S,
        )
        if not r.ok:
            return ReponseLLM("", "groq", p.modele, erreur=f"HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        usage = d.get("usage", {})
        return ReponseLLM(
            texte=d["choices"][0]["message"]["content"],
            provider="groq",
            modele=p.modele,
            tokens_entree=usage.get("prompt_tokens", 0),
            tokens_sortie=usage.get("completion_tokens", 0),
            cout_usd=0.0,
        )

    def _gemini(self, p, systeme, utilisateur, json_attendu, temperature) -> ReponseLLM:
        generation: dict[str, Any] = {"temperature": temperature}
        if json_attendu:
            generation["responseMimeType"] = "application/json"

        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{p.modele}:generateContent",
            params={"key": os.getenv("GEMINI_API_KEY")},
            json={
                "systemInstruction": {"parts": [{"text": systeme}]},
                "contents": [{"role": "user", "parts": [{"text": utilisateur}]}],
                "generationConfig": generation,
            },
            timeout=DELAI_MAX_S,
        )
        if not r.ok:
            return ReponseLLM("", "gemini", p.modele, erreur=f"HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        candidats = d.get("candidates", [])
        if not candidats:
            return ReponseLLM("", "gemini", p.modele, erreur="aucun candidat retourne")
        texte = "".join(part.get("text", "") for part in candidats[0]["content"]["parts"])
        usage = d.get("usageMetadata", {})
        return ReponseLLM(
            texte=texte,
            provider="gemini",
            modele=p.modele,
            tokens_entree=usage.get("promptTokenCount", 0),
            tokens_sortie=usage.get("candidatesTokenCount", 0),
        )

    def _ollama(self, p, systeme, utilisateur, json_attendu, temperature) -> ReponseLLM:
        hote = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        charge: dict[str, Any] = {
            "model": p.modele,
            "messages": [
                {"role": "system", "content": systeme},
                {"role": "user", "content": utilisateur},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_attendu:
            charge["format"] = "json"
        r = requests.post(f"{hote}/api/chat", json=charge, timeout=120)
        if not r.ok:
            return ReponseLLM("", "ollama", p.modele, erreur=f"HTTP {r.status_code}")
        d = r.json()
        return ReponseLLM(
            texte=d.get("message", {}).get("content", ""),
            provider="ollama",
            modele=p.modele,
            tokens_entree=d.get("prompt_eval_count", 0),
            tokens_sortie=d.get("eval_count", 0),
        )


# ----------------------------------------------------------------------
# Extraction JSON tolerante
# ----------------------------------------------------------------------


def extraire_json(texte: str) -> dict[str, Any] | None:
    """Extrait un objet JSON d'une reponse de modele.

    Les modeles encadrent frequemment leur JSON de texte libre ou de blocs de
    code. On tente le parsing direct, puis le bloc balise, puis le premier objet
    equilibre trouve dans la chaine.
    """
    if not texte:
        return None

    try:
        valeur = json.loads(texte)
        return valeur if isinstance(valeur, dict) else None
    except json.JSONDecodeError:
        pass

    bloc = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texte, re.DOTALL)
    if bloc:
        try:
            return json.loads(bloc.group(1))
        except json.JSONDecodeError:
            pass

    debut = texte.find("{")
    if debut == -1:
        return None
    profondeur = 0
    for i in range(debut, len(texte)):
        if texte[i] == "{":
            profondeur += 1
        elif texte[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                try:
                    return json.loads(texte[debut : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


_client: LLMClient | None = None


def client() -> LLMClient:
    """Instance partagee, pour ne detecter les providers qu'une seule fois."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
