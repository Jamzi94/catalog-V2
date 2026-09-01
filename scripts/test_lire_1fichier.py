#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1fichier se lit en requete HTTP simple : ni navigateur, ni cookie.

RELEVE sur page reelle le 2026-09-01 (curl, en-tete de navigateur, rien
d autre) :

    <span class="tier-name">[DLPSGAME.COM] - 02.004 PPSA09482.rar</span>
    <span class="tier-feat">32.49 Go</span>

Ce qui avait masque cette voie : lire_navigateur.py, ecrit pour 1fichier,
pilotait un Chrome et rendait 0 nom sur 5. Il cherchait une cellule de tableau
« nom  taille » qui n existe plus. Le gabarit a change, pas l accessibilite.

CE QUI COMPTE ICI, ET QUI M A COUTE TROIS FOIS AUJOURD HUI : le site LIMITE.
Un balayage a une requete par seconde pendant 24 minutes a rendu 1330 reponses
HTTP 500 sur 1438. Le 500 n est PAS un lien mort — le distinguer du 404 est la
difference entre « fichier supprime » et « je tape trop vite ».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relever_noms import _lire_1fichier                              # noqa: E402

Go = 1024 ** 3

PAGE = ('<html><head><title>1fichier.com: Cloud Storage</title></head><body>'
        '<div class="tier-body">'
        '<span class="tier-name">[DLPSGAME.COM] - 02.004 PPSA09482.rar</span> '
        '<span class="tier-feat">32.49 Go</span>'
        '</div></body></html>')

nom, taille = _lire_1fichier(PAGE)
assert nom == "[DLPSGAME.COM] - 02.004 PPSA09482.rar", nom
assert taille == int(32.49 * Go), taille

# Le nom arrive parfois prefixe d un espace insecable de largeur nulle.
inv = PAGE.replace(">[DLPSGAME", ">​[DLPSGAME")
assert _lire_1fichier(inv)[0] == "[DLPSGAME.COM] - 02.004 PPSA09482.rar"

# Unites anglaises aussi bien que françaises.
assert _lire_1fichier(PAGE.replace("32.49 Go", "2.92 GB"))[1] == int(2.92 * Go)

# TEMOIN : une page sans le gabarit ne rend RIEN plutot qu un nom approchant.
assert _lire_1fichier("<html><title>1fichier.com: Cloud Storage</title></html>") == (None, None)
assert _lire_1fichier("") == (None, None)

# TEMOIN : un nom present mais pas de taille -> le nom seul, pas de chiffre
# invente a partir d un encart de la page.
sans_taille = PAGE.replace('<span class="tier-feat">32.49 Go</span>', "")
assert _lire_1fichier(sans_taille) == ("[DLPSGAME.COM] - 02.004 PPSA09482.rar", None)

print("OK")
