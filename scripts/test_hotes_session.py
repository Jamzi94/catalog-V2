#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""datanodes.to et filekeeper.net : lisibles avec un cookie de session.

    python scripts/test_hotes_session.py

Une requete nue rend 404 sur ces deux hotes — 8 liens sur 8 testes, ce qui
donnait a croire que 1793 liens du catalogue etaient morts. Ils ne le sont pas :
c'est une defense anti-robot. En ouvrant d'abord l'accueil pour recevoir le
cookie de session, la page du fichier repond 200 et porte son nom et sa taille.
Le navigateur faisait exactement cela ; il suffisait de l'imiter.
"""
from __future__ import annotations

import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hoster_size as H  # noqa: E402

DATANODES = (ICI / "fixtures" / "datanodes_page.html").read_text(encoding="utf-8")
FILEKEEPER = (ICI / "fixtures" / "filekeeper_page.html").read_text(encoding="utf-8")

# La couture de test est _FETCH_SESSION : la lecture passe par un opener a
# cookies, pas par le fetcher HTTP ordinaire.
H._FETCH_SESSION = lambda url: DATANODES
assert H.nom_et_taille("https://datanodes.to/tcxz2aii2rgp") == ("PPSA01500.7z", int(67.3 * 1024 ** 3)), \
    H.nom_et_taille("https://datanodes.to/tcxz2aii2rgp")

H._FETCH_SESSION = lambda url: FILEKEEPER
nom, taille = H.nom_et_taille("https://filekeeper.net/l6mv5vbzefmw/x.rar")
assert nom == "[DLPSGAME.COM]-PPSA18888.part06.rar", nom
assert taille == int(1.8 * 1024 ** 3), taille

# TEMOIN NEGATIF — une page qui ne porte pas ces blocs ne doit rien rendre.
# Les deux pages contiennent par ailleurs des tailles d'encart (« 870 KB »,
# « 5 TB ») : une lecture qui prend le premier nombre venu rendrait un chiffre
# plausible et faux.
H._FETCH_SESSION = lambda url: "<html><title>Rien</title><body>5 TB</body></html>"
assert H.nom_et_taille("https://datanodes.to/inconnu") == (None, None)

# TEMOIN NEGATIF — hote non gere : on s'abstient plutot que de deviner.
assert H.nom_et_taille("https://exemple.invalide/x") == (None, None)

print("OK")
