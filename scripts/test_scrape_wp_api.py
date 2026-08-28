#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle du rapprochement entre le libelle de miroir du site et l'hebergeur.

    python scripts/test_scrape_wp_api.py

Sans reseau. Chaque cas porte son temoin negatif : un garde qui rapprocherait
TOUT serait pire que pas de garde — il rendrait un miroir pour un autre.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_wp_api import MIRROR_PATTERNS, motif_pour_indice  # noqa: E402

# Le libelle exact
assert motif_pour_indice("akia") == "akirabox"
assert motif_pour_indice("1file") == "1fichier"

# La variante du site : « Buznew » pour Buzzheavier — le cas qui faisait rendre
# le miroir Akia a la place, sonde du 2026-08-28.
assert motif_pour_indice("buznew") == "buzzheavier"
assert motif_pour_indice("Buzz") == "buzzheavier"

# Temoin negatif : une variante NON listee ne se rapproche de personne. Un repli
# par prefixe a d'abord ete ecrit ici puis retire — un mutant qui portait le
# prefixe de trois a cinq lettres passait la suite intact, donc rien ne le
# tenait. Mieux vaut None qu'un rapprochement que rien ne verifie.
assert motif_pour_indice("buzznew2") is None
assert motif_pour_indice("Vikings") is None

# Temoin negatif : un libelle qui ne designe aucun hebergeur connu ne doit
# rapprocher personne. Sinon le repli « premier lien de la page » revient par
# la fenetre, sous un nom qui n'est pas le sien.
assert motif_pour_indice("zorglub") is None
assert motif_pour_indice("") is None
assert motif_pour_indice(None) is None

# Chaque nom de la table se rapproche d'un motif qui lui appartient vraiment.
motifs_par_nom = {}
for motif, nom in MIRROR_PATTERNS:
    motifs_par_nom.setdefault(nom, []).append(motif)
for nom, motifs in motifs_par_nom.items():
    assert motif_pour_indice(nom) in motifs, (nom, motif_pour_indice(nom), motifs)

print("OK")
