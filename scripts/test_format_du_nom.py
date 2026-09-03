#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le format de CONTENANT lu dans le nom de fichier, et ce qu on en fait.

Un backport n est pas forcement une image exFAT. Mesure du 2026-08-30 sur les
3020 liens de section Backport : 1626 noms disent exFAT, 1 dit FPKG, 1393 se
taisent. Un seul contre-exemple suffit a interdire de DEDUIRE le format — il
faut le LIRE. Et 1563 de ces liens sont au-dessus du seuil correctif contre 217
en dessous : ceux du dessous sont le binaire a deposer, leur etiquette porte
deja la taille, qui en dit plus que le format.

D ou la regle : le format ne s ecrit que s il est VERIFIE par le nom, et
seulement sur le lien qui est le JEU.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import (finalize_package,             # noqa: E402
                              format_du_nom)

Mo, Go = 1024 ** 2, 1024 ** 3


# --- lecture du format ------------------------------------------------------
assert format_du_nom("PPSA08135.exfat") == "exFAT"
assert format_du_nom("[SuperPSX]-Jeu-PPSA1-EUR-exFAT.rar") == "exFAT"
assert format_du_nom("Jeu-PPSA1-FPKG-PS5.rar") == "FPKG"
assert format_du_nom("EP7579-PPSA17599_00-EXP33DLC10000PS5.pkg") == "PKG"
# FPKG prime sur PKG : le mot le contient, et les lire dans l ordre inverse
# ferait passer tous les FPKG pour des PKG.
assert format_du_nom("jeu.fpkg") == "FPKG"
# TEMOINS NEGATIFS : on ne devine pas, et on ne lit pas un mot dans un autre.
assert format_du_nom("PPSA12345-un-jeu-quelconque.rar") is None
assert format_du_nom("packages-du-jeu.rar") is None, "« packages » n est pas « pkg »"
assert format_du_nom("") is None and format_du_nom(None) is None


def _etiq(lien):
    pkg = {"titleId": "PPSA00001", "title": "Jeu", "version": "01.000",
           "downloadLinks": [dict({"url": "https://vikingfile.com/f/a",
                                   "name": "Viki", "version": "01.000"}, **lien)]}
    finalize_package(pkg, {})
    return pkg["downloadLinks"][0]["name"]


# --- BP + format verifie + c est le JEU -> le format s ecrit ----------------
n = _etiq({"group": "Backport 4.xx", "sizeBytes": 40 * Go,
           "fileName": "[SuperPSX]-Jeu-PPSA1-EUR-exFAT.rar"})
assert "BP" in n and "exFAT" in n, n

n = _etiq({"group": "Backport", "sizeBytes": 40 * Go, "fileName": "Jeu-FPKG-PS5.rar"})
assert "BP" in n and "FPKG" in n, n

# --- BP sous le seuil : la TAILLE parle, pas le format ----------------------
n = _etiq({"group": "Backport", "sizeBytes": 91 * Mo, "fileName": "Jeu-exFAT-fix.rar"})
assert "91 Mo" in n and "exFAT" not in n, n

# --- TEMOIN : nom muet -> aucun format invente, meme au-dessus du seuil -----
n = _etiq({"group": "Backport 4.xx", "sizeBytes": 40 * Go,
           "fileName": "PPSA12345-un-jeu-quelconque.rar"})
assert "exFAT" not in n and "FPKG" not in n and "PKG" not in n, n

# --- TEMOIN : sans nom de fichier du tout, rien ne bouge -------------------
n = _etiq({"group": "Backport 4.xx", "sizeBytes": 40 * Go})
# DECISION du 2026-08-30 : « chaque etiquetage affiche la taille du fichier
# quand connu ». L'attente precedente — un BP volumineux n'annonce PAS sa
# taille, la fiche la portant deja — venait d'une economie de pixels. La
# demande la renverse. Cout mesure : troncature de 8,2 % a 10,2 %.
assert n == "[BP 4.xx · 40 Go]", n

# --- hors BP, le format verifie CORRIGE toujours une etiquette qui se trompe
n = _etiq({"group": "Standard", "fileFormat": "PKG", "fileName": "PPSA08135.exfat"})
assert "exFAT" in n and "PKG" not in n, n

print("OK")
