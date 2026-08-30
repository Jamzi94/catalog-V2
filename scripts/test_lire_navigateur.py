#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1fichier : lecture du nom et de la taille, partie ANALYSE (sans navigateur).

    python scripts/test_lire_navigateur.py

1fichier n'expose aucune API anonyme — verifie le 2026-08-30 : tous les
endpoints documentes exigent une cle. La page, elle, porte l'information, mais
derriere une fenetre de consentement qui interdit la lecture par requete nue.
Un navigateur la lit ; ce test couvre la partie qui ne depend pas de lui, la
seule qui puisse etre tenue hors ligne.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lire_navigateur import decouper_cellule  # noqa: E402

Go = 1024 ** 3

# Cellules REELLES relevees le 2026-08-30.
assert decouper_cellule("[SuperPSX]-EA.Sports.UFC.5-PPSA03541-EUR-Game (v01.031)-PS5.part01.rar 10.74 Go") == (
    "[SuperPSX]-EA.Sports.UFC.5-PPSA03541-EUR-Game (v01.031)-PS5.part01.rar", int(10.74 * Go))
nom, taille = decouper_cellule("[DLPSGAME.COM]-01.031 PPSA03541.rar 48.77 Go")
assert nom == "[DLPSGAME.COM]-01.031 PPSA03541.rar", nom
assert taille == int(48.77 * Go), taille

# Unites : Mo et Ko doivent aussi passer, le site est francophone.
assert decouper_cellule("patch.zip 91 Mo")[1] == 91 * 1024 ** 2
assert decouper_cellule("truc.rar 512 Ko")[1] == 512 * 1024

# TEMOIN NEGATIF — une cellule sans taille rend le nom et None, pas un chiffre
# invente ; une cellule vide ne rend rien.
assert decouper_cellule("fichier.rar") == ("fichier.rar", None)
assert decouper_cellule("") == (None, None)
assert decouper_cellule(None) == (None, None)

# TEMOIN NEGATIF — le nom ne doit pas avaler la taille, ni l'inverse. Un nom qui
# contient des chiffres et « Go » ailleurs ne doit pas etre tronque au mauvais
# endroit.
nom, taille = decouper_cellule("Jeu.Go.Edition-PPSA1.rar 2.5 Go")
assert nom == "Jeu.Go.Edition-PPSA1.rar", nom
assert taille == int(2.5 * Go), taille

print("OK")
