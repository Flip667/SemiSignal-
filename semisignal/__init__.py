"""SemiSignal — agent analyste semi-conducteurs (EDGAR + Microsoft Foundry)."""

# Charge les variables d'environnement depuis .env si présent (credentials Foundry).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
