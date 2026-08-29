#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Classer un lien jeu/correctif d'apres le NOM DE FICHIER releve chez l'hebergeur.

    python scripts/test_classer_nom.py

Le nom est un bien meilleur signal que la taille, et il couvre plus de liens.
Validation du 2026-08-30 sur 1206 liens ayant a la fois un nom releve et une
taille mesuree : le classifieur tranche 978 d'entre eux (81 %) et se trompe
8 fois — 99 % d'exactitude sur ce qu'il tranche. Les motifs et leurs taux :
  « backport » 163/163 correctifs · « .zip » 132/132 · « @bestpig » 22/22 ·
  « 4.xx » 115/117 · « .exfat » 5/429 (donc 99 % de jeux) · « partNN » 0/13.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import classer_par_nom  # noqa: E402

# --- correctif ---------------------------------------------------------------
assert classer_par_nom("[SuperPSX]-Jeu-PPSA00001-EUR-Backport 4.xx+ (@BestPig)-PS5.rar") == "correctif"
assert classer_par_nom("PPSA10965-4XX-BADERLINK.zip") == "correctif"
assert classer_par_nom("Jeu 4.xx patch.rar") == "correctif"

# --- jeu ---------------------------------------------------------------------
assert classer_par_nom("PPSA31246.exfat") == "jeu"
assert classer_par_nom("[DLPSGAME.COM]-PPSA01487.part06.rar") == "jeu"

# --- l'ordre compte : un nom qui porte les DEUX marques est un JEU decoupe ou
# une image exFAT, pas un correctif. « Backport ... part03.rar » pese 8 Go.
assert classer_par_nom("[SuperPSX]-Jeu-PPSA1-EUR-Backport (exFAT)-PS5.part03.rar") == "jeu"
assert classer_par_nom("PPSA31246-backport.exfat") == "jeu"

# --- inconnu : on n'invente pas -----------------------------------------------
assert classer_par_nom("file.rar") == "inconnu"
assert classer_par_nom("") == "inconnu"
assert classer_par_nom(None) == "inconnu"

# TEMOIN — le classifieur ne doit pas etre un oui-oui : un nom qui ne porte
# aucune marque reste « inconnu », il ne bascule pas vers la classe majoritaire.
assert classer_par_nom("PPSA00001 v1.000 USA") == "inconnu"

print("OK")
