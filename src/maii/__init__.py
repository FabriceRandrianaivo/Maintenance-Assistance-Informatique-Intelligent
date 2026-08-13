"""mAIntenance & Assistance - assistant intelligent de support informatique.

Le fichier `.env` de la racine est charge des l'import du paquet, afin que les
cles d'acces aux modeles soient disponibles quel que soit le point d'entree :
interface, script de demonstration, evaluation ou tests.
"""

from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    load_dotenv(RACINE / ".env", override=False)
except ImportError:  # l'absence de la dependance ne doit pas bloquer le demarrage
    pass

__all__ = ["RACINE"]
