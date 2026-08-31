#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un lien qui rend 404 est mort : on le marque, et on cesse de l afficher.

MESURE du 2026-08-31 : 601 liens du catalogue restent sans nom chez des
hebergeurs qui se LISENT (vikingfile, datanodes, filekeeper). Sur 50 tires au
sort, 50 rendent HTTP 404. Ce ne sont pas des echecs de lecture — l instrument
est etalonne : 12 liens deja nommes chez les MEMES hotes se relisent 12 fois
sur 12. Ce sont des fichiers supprimes.

Deux couts a les laisser : on les resonde a chaque run pour rien, et surtout
l utilisateur les voit sans savoir qu ils sont morts.

Ils sont donc marques a la collecte, et retires a l affichage — mais JAMAIS au
point de vider une fiche : mieux vaut un lien mort visible que zero lien, qui
ferait croire que le jeu n est pas dans le catalogue.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import _retirer_liens_morts                     # noqa: E402


def _pkgs():
    return [
        # une fiche qui garde des vivants : les morts partent
        {"titleId": "PPSA00001", "downloadLinks": [
            {"url": "https://a/1", "fileName": "jeu.rar"},
            {"url": "https://a/2", "linkDead": True},
            {"url": "https://a/3", "linkDead": True},
        ]},
        # une fiche OU TOUT est mort : on ne la vide pas
        {"titleId": "PPSA00002", "downloadLinks": [
            {"url": "https://b/1", "linkDead": True},
            {"url": "https://b/2", "linkDead": True},
        ]},
        # aucun mort : rien ne bouge
        {"titleId": "PPSA00003", "downloadLinks": [
            {"url": "https://c/1", "fileName": "x.rar"},
        ]},
    ]


pk = _pkgs()
stats = {}
_retirer_liens_morts(pk, stats)
assert [l["url"] for l in pk[0]["downloadLinks"]] == ["https://a/1"], pk[0]
# TEMOIN : la fiche entierement morte garde ses liens. Un catalogue qui cache
# un jeu ment plus qu un catalogue qui montre un lien perime.
assert len(pk[1]["downloadLinks"]) == 2, pk[1]
assert len(pk[2]["downloadLinks"]) == 1, pk[2]
assert stats["liens_morts_retires"] == 2, stats

# TEMOIN : un catalogue sans aucun mort n est pas touche et le compte est 0.
pk2 = [{"titleId": "PPSA1", "downloadLinks": [{"url": "https://z/1"}]}]
s2 = {}
_retirer_liens_morts(pk2, s2)
assert s2["liens_morts_retires"] == 0 and len(pk2[0]["downloadLinks"]) == 1

print("OK")
