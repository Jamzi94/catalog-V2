#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distinguer le BP-JEU du BP-CORRECTIF par la taille.

    python scripts/test_taille_liens.py

Mesure fondatrice (2026-08-30, 114 tailles relevees chez les hebergeurs sur des
liens BP tires au sort) : la distribution est BIMODALE — 49 liens sous 100 Mo,
1 seul dans toute la vallee 133-307 Mo, 58 au-dessus de 1 Go, jusqu'a 101 Go.
Un BP de 45 Mo est le binaire a deposer dans le dossier du jeu ; un BP de 40 Go
est le jeu lui-meme. Le seuil est pose au MILIEU de la vallee.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
from pegasus_finalize import (  # noqa: E402
    SEUIL_CORRECTIF, _propager_tailles, _taille_courte, finalize_package,
)

Mo = 1024 ** 2
Go = 1024 ** 3

# --- format court -----------------------------------------------------------
assert _taille_courte(45 * Mo) == "45 Mo"
assert _taille_courte(2 * Mo) == "2 Mo"
assert _taille_courte(int(1.1 * Go)) == "1.1 Go"
assert _taille_courte(101 * Go) == "101 Go"
assert _taille_courte(None) == ""
assert _taille_courte(0) == ""

# --- propagation dans la rubrique -------------------------------------------
# Les liens d'une meme rubrique sont le MEME fichier sur plusieurs hebergeurs :
# une seule sonde suffit. C'est ce qui fait passer la couverture de 32 % a 94 %.
pkg = {"downloadLinks": [
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport 4.xx",
     "version": "01.000", "region": "EUR", "sizeBytes": 45 * Mo},
    {"name": "Akia", "url": "https://akirabox.com/b/file", "group": "Backport 4.xx",
     "version": "01.000", "region": "EUR"},
    # rubrique DIFFERENTE : ne doit RIEN recevoir, sinon on colle la taille du
    # correctif sur le jeu complet.
    {"name": "Data", "url": "https://datanodes.to/c", "group": "Standard",
     "version": "01.000", "region": "EUR"},
]}
_propager_tailles(pkg)
L = pkg["downloadLinks"]
assert L[1].get("sizeBytes") == 45 * Mo, L[1]
assert L[1].get("_tailleHeritee") is True, L[1]
assert "sizeBytes" not in L[2], L[2]

# Temoin negatif : une taille propre n'est jamais ecrasee par celle d'un voisin.
pkg2 = {"downloadLinks": [
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport",
     "sizeBytes": 45 * Mo},
    {"name": "Akia", "url": "https://akirabox.com/b/file", "group": "Backport",
     "sizeBytes": 40 * Go},
]}
_propager_tailles(pkg2)
assert pkg2["downloadLinks"][1]["sizeBytes"] == 40 * Go

# --- l'etiquette -------------------------------------------------------------
def _noms(liens, version="01.000"):
    p = {"titleId": "PPSA00001", "title": "Jeu", "version": version,
         "fileFormat": ["PKG"], "downloadLinks": liens}
    finalize_package(p, collections.defaultdict(int))
    return [l["name"] for l in p["downloadLinks"]]

# Un BP petit annonce sa taille : l'utilisateur voit tout de suite que ce n'est
# pas le jeu.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a",
               "group": "Backport 4.xx", "version": "01.000", "sizeBytes": 45 * Mo}])
assert noms[0] == "[BP 4.xx · 45 Mo] Viki", noms

# Un BP volumineux ne l'annonce pas : c'est le jeu, la fiche porte deja sa
# taille, et les pixels sont comptes.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a",
               "group": "Backport 4.xx", "version": "01.000", "sizeBytes": 40 * Go}])
assert noms[0] == "[BP 4.xx] Viki", noms

# Temoin negatif : un lien NON BP de meme taille ne recoit rien — la question
# posee ne concerne que les backports.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a",
               "group": "exFAT", "version": "01.000", "sizeBytes": 45 * Mo}])
assert noms[0] == "[exFAT] Viki", noms

# Temoin negatif : sans taille, rien n'est invente.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a",
               "group": "Backport 4.xx", "version": "01.000"}])
assert noms[0] == "[BP 4.xx] Viki", noms

# INTEGRATION : la taille HERITEE doit atteindre l'etiquette. C'est tout
# l'interet de la propagation — le miroir akirabox n'est pas sondable, mais il
# partage sa rubrique avec un vikingfile qui l'est.
noms = _noms([
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport 4.xx",
     "version": "01.000", "sizeBytes": 45 * Mo},
    {"name": "Akia", "url": "https://akirabox.com/b/file", "group": "Backport 4.xx",
     "version": "01.000"},
])
assert noms == ["[BP 4.xx · 45 Mo] Viki", "[BP 4.xx · 45 Mo] Akia"], noms

# Le seuil est bien dans la vallee mesuree, pas sur un mode.
assert 133 * Mo <= SEUIL_CORRECTIF <= 307 * Mo, SEUIL_CORRECTIF

print("OK")
