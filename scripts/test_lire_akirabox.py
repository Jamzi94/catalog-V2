#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analyse d'une page akirabox — la partie qui ne depend pas de FlareSolverr.

    python scripts/test_lire_akirabox.py

ETAT : les quatre gabarits testes ici sont ceux des QUATRE AUTRES hebergeurs
deja ouverts (datanodes, buzzheavier, datavaults, filekeeper). Aucun n'a encore
ete confronte a une VRAIE page akirabox : celle-ci resiste a tout ce qu'on sait
faire sans FlareSolverr. Tant qu'une capture reelle n'a pas ete versee en
fixture, le comportement de extraire_nom_taille sur akirabox est [NM].

Ce test garantit deux choses en attendant :
  - les gabarits connus sont bien reconnus, chacun avec sa taille ;
  - une page qui ne dit rien rend (None, None) — jamais un chiffre invente.
"""
from __future__ import annotations

import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
from lire_akirabox import extraire_nom_taille  # noqa: E402

Go = 1024 ** 3

# Gabarit 1 — og:title « nom (taille) », celui de datanodes.
page = ('<html><head><meta property="og:title" content="PPSA01500.7z (67.3 GB)">'
        '</head><body></body></html>')
assert extraire_nom_taille(page) == ("PPSA01500.7z", int(67.3 * Go)), extraire_nom_taille(page)

# Gabarit 2 — champ cache « fname », celui de datavaults.
page = ('<html><title>Telechargement PPSA21022</title>'
        '<input type="hidden" name="fname" value="PPSA21022.exfat">'
        '<span>40.4GB</span></html>')
nom, taille = extraire_nom_taille(page)
assert nom == "PPSA21022.exfat", nom
assert taille == int(40.4 * Go), taille

# Gabarit 3 — id="dl-filename", celui de filekeeper.
page = '<html><div id="dl-filename">jeu.part06.rar</div><span>1.8 GB</span></html>'
assert extraire_nom_taille(page)[0] == "jeu.part06.rar"

# Gabarit 4 — le titre EST le nom, celui de buzzheavier.
page = '<html><title>PPSA02387.exfat</title><span class="size">40.4GB</span></html>'
assert extraire_nom_taille(page)[0] == "PPSA02387.exfat"

# TEMOIN NEGATIF — le nom du site n'est pas un nom de fichier.
assert extraire_nom_taille('<html><title>Akirabox - Free file hosting</title></html>') == (None, None)

# TEMOIN NEGATIF — page muette, page vide : rien, et surtout pas un chiffre.
assert extraire_nom_taille("<html><body>Just a moment...</body></html>") == (None, None)
assert extraire_nom_taille("") == (None, None)
assert extraire_nom_taille(None) == (None, None)

# TEMOIN NEGATIF — une taille lointaine ne doit PAS etre servie comme celle du
# fichier. C'est le piege rencontre chez datavaults, dont la page affiche
# « Max upload 1 GB » et « Download volume 15 GB » sans jamais donner la taille.
page = ('<html><input name="fname" value="jeu.rar">' + ("x" * 6000) +
        '<b>15 GB</b></html>')
assert extraire_nom_taille(page) == ("jeu.rar", None), extraire_nom_taille(page)

print("OK")
