#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controle des deux gardes anti-doublons de pegasus_finalize.

    python scripts/test_pegasus_finalize.py

Chaque garde porte son temoin negatif — ce qu'il ne doit PAS toucher. Sans lui,
un garde qui mordrait tout (dedoublonner deux fichiers distincts, numeroter un
libelle unique) passerait pour correct.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import (  # noqa: E402
    _clean_links, _number_parts, _purger_liens_etrangers,
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

print("OK")
