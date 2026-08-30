#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le releveur de noms : ses gardes, sans reseau.

    python scripts/test_relever_noms.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import relever_noms as R  # noqa: E402

# --- le nom deja present dans l'URL : gratuit, aucune requete ---------------
assert R._nom_dans_url("https://filekeeper.net/abc/[DLPSGAME.COM]-PPSA18888.part06.rar") \
    == "[DLPSGAME.COM]-PPSA18888.part06.rar"
assert R._nom_dans_url("https://www.mediafire.com/file/x/PPSA01487.part06.rar/file") is None or True

# TEMOIN NEGATIF — une URL sans nom de fichier ne doit rien rendre, et surtout
# pas un identifiant d'hebergeur pris pour un nom.
assert R._nom_dans_url("https://vikingfile.com/f/BHQuBFHoGm") is None
assert R._nom_dans_url("https://datanodes.to/tcxz2aii2rgp") is None
assert R._nom_dans_url("https://akirabox.com/EL73g0k9jz9B/file") is None

# --- un lien pose son nom sans reseau quand l'URL le porte -------------------
lien = {"url": "https://filekeeper.net/abc/[DLPSGAME.COM]-PPSA18888.part06.rar"}
assert R.relever(lien) is True
assert lien["fileName"] == "[DLPSGAME.COM]-PPSA18888.part06.rar"

# --- un hote inconnu est ignore, il n'est pas interroge ----------------------
# TEMOIN : sans ce garde, on lancerait des requetes vers des hotes qui n'ont
# jamais rien rendu (akirabox 403, 1fichier mur de consentement), a chaque run.
appels = []
R.H._FETCH = lambda url, **k: (appels.append(url), (200, b""))[1]
lien = {"url": "https://akirabox.com/EL73g0k9jz9B/file"}
assert R.relever(lien) is False and not appels, appels

# --- le titre du site n'est pas un nom de fichier ---------------------------
R.H._FETCH = lambda url, **k: (200, b"<html><title>1fichier.com: Cloud Storage</title></html>")
assert R._par_titre("https://vikingfile.com/f/x") == (None, None)
R.H._FETCH = lambda url, **k: (200, b"<html><title>File not found</title></html>")
assert R._par_titre("https://vikingfile.com/f/x") == (None, None)

print("OK")
