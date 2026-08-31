#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un lien dont le FICHIER nomme un autre jeu n appartient pas a cette fiche.

DECOUVERTE du 2026-08-30, en regardant la fiche « DOOM Eternal » (PPSA01981) :
elle portait des liens vers Superliminal, Death Stranding, Eriksholm et Shin
Megami Tensei. Les 371 « liens etrangers » reperes plus tot par editionId
n avaient pas de cause tracable ; les noms de fichiers releves chez les
hebergeurs depuis les rendent enfin VISIBLES.

MESURE sur les 9963 liens dont le nom porte un titleId Sony : 1295 en portent
un DIFFERENT de leur fiche. Trois cas, et un seul est fautif :

  A. 214  meme jeu, autre edition — « Horizon Forbidden West » recevant
          « Horizon.Forbidden.West.Complete.Edition-PPSA17905 ». LEGITIME,
          on n y touche pas : le nom du fichier evoque le titre de la fiche.
  B. 414  AUTRE jeu, dont la fiche EXISTE et dont le nom correspond a SON
          titre. Deux preuves concordantes. Sur ces 414, 376 sont deja
          presents sur la bonne fiche (a purger, rien ne se perd) et 38 n y
          sont pas (a deplacer).
  C. 667  indetermine — titleId inconnu, ou nom qui n evoque aucun titre.
          On ne touche pas : un doute ne se resout pas en supprimant.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import _replacer_liens_par_nom                 # noqa: E402


def _cat():
    return [
        {"titleId": "PPSA01981", "title": "DOOM Eternal", "downloadLinks": [
            {"url": "https://a/doom", "fileName": "PPSA01981.exfat"},
            # intrus DEJA present sur sa bonne fiche -> purge
            {"url": "https://a/super", "fileName": "[SuperPSX]-Superliminal-PPSA06084-USA.rar"},
            # intrus ABSENT de sa bonne fiche -> deplace
            {"url": "https://a/aew", "fileName": "PPSA09351 AEW Fight Forever.rar"},
            # meme jeu, autre edition : le nom evoque le titre de la fiche
            {"url": "https://a/ed", "fileName": "DOOM.Eternal.Deluxe-PPSA01982-EUR.rar"},
            # titleId inconnu du catalogue -> indetermine, on ne touche pas
            {"url": "https://a/x", "fileName": "PPSA99999-un-truc.rar"},
            # aucun titleId dans le nom -> hors sujet
            {"url": "https://a/y", "fileName": "un-fichier-sans-id.rar"},
        ]},
        {"titleId": "PPSA06084", "title": "Superliminal", "downloadLinks": [
            {"url": "https://a/super", "fileName": "[SuperPSX]-Superliminal-PPSA06084-USA.rar"}]},
        {"titleId": "PPSA09351", "title": "AEW Fight Forever", "downloadLinks": []},
    ]


pk = _cat()
stats = {}
_replacer_liens_par_nom(pk, stats)
doom = [l["url"] for l in pk[0]["downloadLinks"]]
aew = [l["url"] for l in pk[2]["downloadLinks"]]

# l intrus deja present ailleurs disparait de DOOM, sans etre duplique
assert "https://a/super" not in doom, doom
assert [l["url"] for l in pk[1]["downloadLinks"]].count("https://a/super") == 1

# l intrus absent de sa fiche y est DEPLACE, pas copie
assert "https://a/aew" not in doom, doom
assert aew == ["https://a/aew"], aew

# TEMOINS — rien d autre ne bouge
assert "https://a/doom" in doom, "le lien du bon jeu a saute"
assert "https://a/ed" in doom, "une autre edition du MEME jeu n est pas un intrus"
assert "https://a/x" in doom, "titleId inconnu : le doute ne se resout pas en supprimant"
assert "https://a/y" in doom, "nom sans titleId : hors sujet"
assert len(doom) == 4, doom

print("OK")
