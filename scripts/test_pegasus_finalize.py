#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle des deux gardes anti-doublons de pegasus_finalize.

    python scripts/test_pegasus_finalize.py

Chaque garde porte son temoin negatif — ce qu'il ne doit PAS toucher. Sans lui,
un garde qui mordrait tout (dedoublonner deux fichiers distincts, numeroter un
libelle unique) passerait pour correct.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import (  # noqa: E402
    _absorber_fiches_placeholder, _clean_links, _number_parts,
    _purger_liens_etrangers, finalize_package,
)


def _pkg(*urls, nom="Viki"):
    return {"downloadLinks": [{"name": nom, "url": u} for u in urls]}


# A) Entite HTML : `&amp;` et `&` designent le MEME fichier -> un seul lien.
p = _pkg("https://1fichier.com/?abc&af=1", "https://1fichier.com/?abc&amp;af=1")
assert _clean_links(p) == 1, p["downloadLinks"]
assert p["downloadLinks"][0]["url"] == "https://1fichier.com/?abc&af=1"

# A) Temoin negatif : deux fichiers differents du meme hote restent deux liens.
p = _pkg("https://1fichier.com/?abc&af=1", "https://1fichier.com/?xyz&af=1")
assert _clean_links(p) == 2

# B) Libelles identiques, URL opaques : rang d'affichage.
p = _pkg("https://vikingfile.com/f/aaa", "https://vikingfile.com/f/bbb")
_number_parts(p)
assert [l["name"] for l in p["downloadLinks"]] == ["Viki #01", "Viki #02"]

# B) Temoin negatif : un vrai numero de partie garde « n/N ».
p = _pkg("https://x.tld/jeu.part1.rar", "https://x.tld/jeu.part2.rar")
_number_parts(p)
assert [l["name"] for l in p["downloadLinks"]] == ["Viki 01/02", "Viki 02/02"]

# B) Temoin negatif : un libelle deja unique n'est pas numerote.
p = {"downloadLinks": [{"name": "Viki", "url": "https://vikingfile.com/f/aaa"},
                       {"name": "Rootz", "url": "https://rootz.so/d/bbb"}]}
_number_parts(p)
assert [l["name"] for l in p["downloadLinks"]] == ["Viki", "Rootz"]

# C) Un lien dont l'editionId nomme une autre fiche est retire de l'usurpatrice
# et conserve chez son proprietaire.
def _cat():
    return [
        {"titleId": "PPSA00001", "title": "Proprietaire", "downloadLinks": [
            {"name": "Viki", "url": "https://h.tld/a", "editionId": "PPSA00001"}]},
        {"titleId": "PPSA00002", "title": "Usurpatrice", "downloadLinks": [
            {"name": "Viki", "url": "https://h.tld/a"},
            {"name": "Viki", "url": "https://h.tld/propre"}]},
    ]
st = {"liens_etrangers": 0, "fiches_delestees": 0}
c = _cat(); _purger_liens_etrangers(c, st)
assert [l["url"] for l in c[0]["downloadLinks"]] == ["https://h.tld/a"], c[0]
assert [l["url"] for l in c[1]["downloadLinks"]] == ["https://h.tld/propre"], c[1]
assert st["liens_etrangers"] == 1 and st["fiches_delestees"] == 1, st

# C) Temoin negatif : sans editionId, un lien partage n'accuse personne, rien ne bouge.
st = {"liens_etrangers": 0, "fiches_delestees": 0}
c = _cat(); del c[0]["downloadLinks"][0]["editionId"]
_purger_liens_etrangers(c, st)
assert st["liens_etrangers"] == 0 and len(c[1]["downloadLinks"]) == 2, (st, c[1])

# C) Temoin negatif : proprietaire annonce absent du catalogue -> on ne touche a rien.
st = {"liens_etrangers": 0, "fiches_delestees": 0}
c = _cat(); c[0]["downloadLinks"][0]["editionId"] = "PPSA99999"; c[0]["titleId"] = "PPSA00003"
_purger_liens_etrangers(c, st)
assert st["liens_etrangers"] == 0, st

# C) Temoin negatif : editionId contradictoires sur la meme URL -> personne n'est
# designe, on s'abstient.
st = {"liens_etrangers": 0, "fiches_delestees": 0}
c = _cat(); c[1]["downloadLinks"][0]["editionId"] = "PPSA00002"
_purger_liens_etrangers(c, st)
assert st["liens_etrangers"] == 0, st

# D) Une fiche a identifiant fabrique est versee dans la vraie fiche du jeu.
st = {"fiches_absorbees": 0}
c = [{"titleId": "PPSA00001", "title": "Avatar: Frontiers of Pandora",
      "downloadLinks": [{"name": "Viki", "url": "https://h.tld/a"}]},
     {"titleId": "GAME_12345", "title": "Avatar Frontiers of Pandora",
      "downloadLinks": [{"name": "Viki", "url": "https://h.tld/a"},
                        {"name": "Rootz", "url": "https://h.tld/b"}]}]
g = _absorber_fiches_placeholder(c, st)
assert len(g) == 1 and g[0]["titleId"] == "PPSA00001", g
assert [l["url"] for l in g[0]["downloadLinks"]] == ["https://h.tld/a", "https://h.tld/b"], g[0]
assert st["fiches_absorbees"] == 1

# D) Temoin negatif : deux titleId REELS ne fusionnent jamais, meme titre identique
# (Bugsnax PPSA01502/01503 sont deux editions regionales, pas un doublon).
st = {"fiches_absorbees": 0}
c = [{"titleId": "PPSA01502", "title": "Bugsnax", "downloadLinks": []},
     {"titleId": "PPSA01503", "title": "Bugsnax", "downloadLinks": []}]
assert len(_absorber_fiches_placeholder(c, st)) == 2 and st["fiches_absorbees"] == 0

# D) Temoin negatif : sans fiche reelle du meme titre, la fiche fabriquee reste.
st = {"fiches_absorbees": 0}
c = [{"titleId": "GAME_99999", "title": "Jeu inconnu", "downloadLinks": []}]
assert len(_absorber_fiches_placeholder(c, st)) == 1 and st["fiches_absorbees"] == 0

# D) Temoin negatif : deux fiches reelles candidates -> on ne choisit pas.
st = {"fiches_absorbees": 0}
c = [{"titleId": "PPSA00001", "title": "Bugsnax", "downloadLinks": []},
     {"titleId": "PPSA00002", "title": "Bugsnax", "downloadLinks": []},
     {"titleId": "GAME_11111", "title": "Bugsnax", "downloadLinks": []}]
assert len(_absorber_fiches_placeholder(c, st)) == 3 and st["fiches_absorbees"] == 0

# E) L'etiquette ne repete pas la version de la fiche, mais l'ecrit quand elle
# differe — c'est-a-dire quand elle distingue deux liens.
def _etiquettes(version, liens):
    pkg = {"titleId": "PPSA00001", "title": "Jeu", "version": version,
           "fileFormat": ["PKG"], "downloadLinks": liens}
    finalize_package(pkg, collections.defaultdict(int))
    return [l["name"] for l in pkg["downloadLinks"]]

noms = _etiquettes("01.031", [
    {"name": "Viki", "url": "https://vikingfile.com/f/a", "group": "Standard", "version": "01.031"},
    {"name": "Rootz", "url": "https://rootz.so/d/b", "group": "Backport", "version": "01.005"},
])
assert noms[0] == "[PKG] Viki", noms          # meme version que la fiche -> tue
assert noms[1] == "[v01.005 · Backport] Rootz", noms   # version differente -> ecrite

# E) Temoin negatif : sans format ni region, l'etiquette garderait le seul nom
# d'hote (deja affiche dessous) — la version revient.
noms = _etiquettes("01.031", [{"name": "Viki", "url": "https://vikingfile.com/f/a",
                               "group": "", "version": "01.031"}])
assert noms[0].startswith("["), noms

# F) Une URL qui ne mene a aucun fichier est retiree ; un vrai lien du meme
# hebergeur ne le serait pas (temoin negatif).
p2 = {"downloadLinks": [
    {"name": "Mirror", "url": "https://rapidgator.net/article/premium/ref/21929"},
    {"name": "Promo", "url": "https://rapidgator.net/images/pics/142_782x9.jpg"},
    {"name": "Fichier", "url": "https://rapidgator.net/file/abc123"}]}
assert _clean_links(p2) == 1, p2["downloadLinks"]
assert p2["downloadLinks"][0]["name"] == "Fichier", p2["downloadLinks"]

print("OK")
