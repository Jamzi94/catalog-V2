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

# --- l'heritage de taille est INTERDIT ---------------------------------------
# Il avait ete pose le 2026-08-30 sur l'hypothese « une rubrique = un fichier ».
# TEMOIN : en sondant un SECOND miroir de 61 rubriques deja mesurees, 53 rendent
# une taille DIFFERENTE et 15 changent de classement. Exemple mesure : sur
# Lollipop Chainsaw RePoP, un lien Mediafire de 43 Mo avait herite de 39,7 Go.
# La cause est que `group` ne capture pas l'identite de la rubrique : il vaut
# souvent None ou « Standard » pour des lignes source differentes, et une meme
# grappe melangeait 10 liens dont un correctif et le jeu.
# Une taille fausse est pire qu'une taille absente : on n'affiche que ce qui a
# ete MESURE sur CE lien.
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
assert "sizeBytes" not in L[1], ("l heritage a resservi", L[1])
assert "sizeBytes" not in L[2], L[2]

# Une taille propre reste evidemment intacte.
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

# INTEGRATION : seul le lien MESURE porte sa taille. Le miroir non sondable
# n'herite de rien — c'est le prix de l'exactitude, et il est assume.
noms = _noms([
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport 4.xx",
     "version": "01.000", "sizeBytes": 45 * Mo},
    {"name": "Akia", "url": "https://akirabox.com/b/file", "group": "Backport 4.xx",
     "version": "01.000"},
])
assert noms == ["[BP 4.xx · 45 Mo] Viki", "[BP 4.xx] Akia"], noms

# Le seuil doit tomber dans l'intervalle OU AUCUNE TAILLE N'A ETE OBSERVEE.
# Sur les 214 tailles mesurees de la section « Backport » — la seule population
# ou la vallee existe reellement (densite au creux : 3,5 % du pic, contre 88,6 %
# pour « Backport N.xx » qui n'a aucun correctif sur 398 mesures) — les deux
# observations qui encadrent le creux sont 217 Mo et 893 Mo. Tout seuil entre
# les deux donne EXACTEMENT le meme classement : 119 correctifs, 95 jeux.
# Ce n'est donc plus un choix, c'est un intervalle mesure.
assert 217 * Mo < SEUIL_CORRECTIF < 893 * Mo, SEUIL_CORRECTIF

# --- le NOM DE FICHIER prime sur la taille ------------------------------------
# Il tranche 81 % des liens contre 60 % pour la taille, avec 99 % d'exactitude,
# et il est disponible chez des hebergeurs dont la taille ne l'est pas.

# Nom disant « backport » : correctif, meme SANS taille mesuree.
noms = _noms([{"name": "Akia", "url": "https://akirabox.com/a/file", "group": "Backport",
               "version": "01.000",
               "fileName": "[SuperPSX]-Jeu-PPSA1-EUR-Backport 4.xx+ (@BestPig)-PS5.rar"}])
assert noms[0] == "[BP · fix] Akia", noms

# Avec la taille en plus, c'est la taille qui s'affiche : elle en dit davantage.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport",
               "version": "01.000", "sizeBytes": 91 * Mo,
               "fileName": "Jeu-Backport 4.xx.zip"}])
assert noms[0] == "[BP · 91 Mo] Viki", noms

# TEMOIN — le nom qui dit JEU l'emporte sur une taille sous le seuil. Un
# « .exfat » de 300 Mo reste une image, pas un binaire a deposer.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport",
               "version": "01.000", "sizeBytes": 300 * Mo,
               "fileName": "PPSA31246.exfat"}])
assert noms[0] == "[BP] Viki", noms

# TEMOIN NEGATIF — un nom muet ne fait rien basculer : la taille reprend la main.
noms = _noms([{"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Backport",
               "version": "01.000", "sizeBytes": 91 * Mo, "fileName": "file.rar"}])
assert noms[0] == "[BP · 91 Mo] Viki", noms

print("OK")
