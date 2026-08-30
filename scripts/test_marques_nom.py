#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ce que le NOM DE FICHIER ajoute a l'etiquette.

    python scripts/test_marques_nom.py

Mesure du 2026-08-30 sur 8575 liens dont le nom a ete releve chez l'hebergeur :
  DLC        le nom l'affirme 653 fois, l'etiquette 438 — 341 que l'etiquette ignore
  multipart  1110 noms portent un numero de partie ; sur 354 liens ou un rang
             « #n » est affiche, il ne vaut le VRAI numero que 45 fois (12 %)

Regle : le nom AJOUTE, il ne retire jamais. L'etiquette dit DLC 126 fois la ou
le nom se tait — c'est la source qui le sait, on ne l'efface pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import marques_du_nom, numero_de_partie  # noqa: E402

# --- marques ----------------------------------------------------------------
assert "DLC" in marques_du_nom("[SuperPSX]-Sonic-PPSA17597-USA-DLC (@Pkykzhack)-PS5.rar")
assert "DLC" in marques_du_nom("All_7DLCs_High-Speed007.rar")
assert "DLC" in marques_du_nom("DLC_Psykzhack.rar")
assert "exFAT" in marques_du_nom("PPSA31246.exfat")
assert "Backport" in marques_du_nom("Jeu-Backport 4.xx+ (@BestPig).rar")
assert "Fix" in marques_du_nom("[SuperPSX]-Alone.In.The.Dark-PPSA08240-USA-(Fix-6.xx)-PS5.rar")

# TEMOIN NEGATIF — on ne voit pas ce qui n'est pas ecrit. « dlc » doit etre un
# mot, pas une sous-chaine attrapee au hasard dans un identifiant.
assert marques_du_nom("PPSA01500.7z") == set()
assert "DLC" not in marques_du_nom("abcdlcdef.rar")
assert marques_du_nom("") == set()
assert marques_du_nom(None) == set()

# --- numero de partie -------------------------------------------------------
assert numero_de_partie("[DLPSGAME.COM]-PPSA01487.part06.rar") == 6
assert numero_de_partie("jeu.part1.rar") == 1
assert numero_de_partie("Jeu part 12.rar") == 12
# TEMOIN NEGATIF — pas de numero, pas d'invention. Et « part » doit etre un mot :
# un identifiant d'hebergeur ne doit pas passer pour un numero de partie.
assert numero_de_partie("PPSA31246.exfat") is None
assert numero_de_partie("departement3.rar") is None
assert numero_de_partie(None) is None

# --- integration dans l'etiquette -------------------------------------------
import collections  # noqa: E402
from pegasus_finalize import finalize_package  # noqa: E402


def _noms(liens, version="01.000", fmt=None):
    p = {"titleId": "PPSA00001", "title": "Jeu", "version": version,
         "fileFormat": fmt or ["PKG"], "downloadLinks": liens}
    finalize_package(p, collections.defaultdict(int))
    return [l["name"] for l in p["downloadLinks"]]


# Le nom dit DLC, la source l'avait perdu : l'etiquette le retrouve.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard",
               "version": "01.000",
               "fileName": "[SuperPSX]-Sonic-PPSA17597-USA-DLC (@Pkykzhack)-PS5.rar"}])
assert "DLC" in noms[0], noms

# TEMOIN NEGATIF — on n'ajoute pas ce qui est deja la, ni en double.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "DLC",
               "version": "01.000", "fileName": "All_7DLCs.rar"}])
assert noms[0].count("DLC") == 1, noms

# TEMOIN NEGATIF — un nom muet n'ajoute rien.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard",
               "version": "01.000", "fileName": "PPSA01500.7z"}])
assert "DLC" not in noms[0] and "Fix" not in noms[0], noms

# Le VRAI numero de partie remplace le rang d'affichage. Deux liens de meme
# libelle dont les noms disent part06 et part02 doivent sortir 06/06 et 02/06,
# pas #01 et #02 dans l'ordre du catalogue.
noms = _noms([
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard",
     "version": "01.000", "fileName": "[DLPSGAME.COM]-PPSA01487.part06.rar"},
    {"name": "Viki", "url": "https://vikingfile.com/f/b", "group": "Standard",
     "version": "01.000", "fileName": "[DLPSGAME.COM]-PPSA01487.part02.rar"},
])
assert noms[0].endswith("06/06") and noms[1].endswith("02/06"), noms

# TEMOIN NEGATIF — sans numero dans les noms, on retombe sur le rang « #n », qui
# n'affirme aucun ordre.
noms = _noms([
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard", "version": "01.000"},
    {"name": "Viki", "url": "https://vikingfile.com/f/b", "group": "Standard", "version": "01.000"},
])
assert noms[0].endswith("#01") and noms[1].endswith("#02"), noms

# --- la REGION lue dans le nom ----------------------------------------------
# Mesure du 2026-08-30 : 257 liens portent une region des DEUX cotes, 254
# s'accordent (99 %). Et 2788 la portent dans le NOM sans l'avoir dans le champ
# — l'information est la, elle n'etait pas lue.
from pegasus_finalize import region_du_nom  # noqa: E402

assert region_du_nom("[SuperPSX]-Dakar.Desert.Rally-PPSA04477-USA-PS5.rar") == "USA"
assert region_du_nom("Biomutant PPSA06255 v01.003.000 EUR.rar") == "EUR"
assert region_du_nom("[SuperPSX]-Jeu-PPSA1-JAP-Game.rar") == "JPN"

# TEMOIN NEGATIF — trois lettres majuscules ne font pas une region. « RAR »,
# « PKG », « USB » ne doivent rien declencher, sinon on etiquette au hasard.
assert region_du_nom("PPSA01500.7z") is None
assert region_du_nom("jeu-PKG-PS5.rar") is None
assert region_du_nom("MOUSA_edition.rar") is None
assert region_du_nom(None) is None

# Le champ de la source PRIME : quand les deux parlent, on ne remplace pas une
# region relevee au scraping par une lecture de nom de fichier. Les 3 desaccords
# mesures ne tranchent pas en faveur du nom — ils signalent un lien recolle.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard",
               "version": "01.000", "region": "USA",
               "fileName": "Biomutant PPSA06255 v01.003.000 EUR.rar"}])
assert "USA" in noms[0] and "EUR" not in noms[0], noms

# ... mais quand le champ est vide, le nom comble.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard",
               "version": "01.000",
               "fileName": "[SuperPSX]-Dakar.Desert.Rally-PPSA04477-USA-PS5.rar"}])
assert "USA" in noms[0], noms

print("OK")
