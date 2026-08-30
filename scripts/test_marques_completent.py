#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le nom de fichier complete l etiquette sur Backport et exFAT, sans l ecraser.

POURQUOI ce test existe. finalize_package ne consommait que DLC et Fix parmi
les marques du nom, sur cet argument ecrit dans le code : « Backport vient deja
de la section, mieux renseignee, 2407 contre 1313 ». Cet argument compare des
VOLUMES. Il ne dit rien du cas ou la section se TAIT et le nom PARLE — et c est
exactement ce cas qui produisait 551 des 664 contradictions mesurees le
2026-08-30 en confrontant les 6507 liens comparables a leur nom de fichier :

    fichier  « PPSA02225-Ghost of Tsushima V02.024 Backport 4.XX By BA »
    etiquette « [PKG · v2.024] »            -> mention Backport absente

    fichier  « PPSA08135.exfat »
    etiquette « [PKG] »                     -> le fichier dit exFAT, pas PKG

Le nom AJOUTE ou CORRIGE, il n invente jamais : le dernier temoin le tient.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import finalize_package                        # noqa: E402


def _etiq(liens):
    pkg = {"titleId": "PPSA00001", "title": "Jeu", "downloadLinks": liens}
    finalize_package(pkg, {})
    return [l.get("name") for l in pkg["downloadLinks"]]


# --- Backport : la section se tait, le nom parle -----------------------------
n = _etiq([{"url": "https://a/1", "name": "Viki", "group": "Standard",
            "fileFormat": "PKG", "version": "02.024",
            "fileName": "PPSA02225-Ghost of Tsushima V02.024 Backport 4.XX By BA"}])
assert "BP" in n[0], n

# --- ... mais elle ne se repete pas quand la section le dit deja -------------
n = _etiq([{"url": "https://a/2", "name": "Viki", "group": "Backport 4.xx",
            "fileFormat": "exFAT", "version": "01.000",
            "fileName": "jeu Backport 4.XX.rar"}])
assert n[0].count("BP") == 1, n

# --- exFAT contre PKG : le fichier tranche, ce n est pas un ajout ------------
n = _etiq([{"url": "https://a/3", "name": "Viki", "group": "Standard",
            "fileFormat": "PKG", "version": "01.000", "fileName": "PPSA08135.exfat"}])
assert "exFAT" in n[0] and "PKG" not in n[0], n

# --- ... et rien ne bouge si l etiquette dit deja exFAT ----------------------
n = _etiq([{"url": "https://a/4", "name": "Viki", "group": "exFAT",
            "fileFormat": "exFAT", "version": "01.000", "fileName": "jeu.exfat"}])
assert n[0].count("exFAT") == 1, n

# --- TEMOIN : un nom MUET ne fabrique aucune mention ------------------------
# Sans lui, les assertions ci-dessus passeraient sur un code qui colle « BP » et
# « exFAT » partout, ce qui serait la meme faute a l envers.
muet = _etiq([{"url": "https://a/5", "name": "Viki", "group": "Standard",
               "fileFormat": "PKG", "version": "01.000",
               "fileName": "PPSA12345-un-jeu-quelconque.rar"}])
assert "BP" not in muet[0] and "exFAT" not in muet[0], muet

# --- TEMOIN : sans nom de fichier du tout, l etiquette est celle de la source
sans = _etiq([{"url": "https://a/6", "name": "Viki", "group": "Standard",
               "fileFormat": "PKG", "version": "01.000"}])
assert "BP" not in sans[0] and "exFAT" not in sans[0], sans

print("OK")
