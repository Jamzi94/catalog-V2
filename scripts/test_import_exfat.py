#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Les liens du flux exFAT doivent DIRE qu'ils sont exFAT.

    python scripts/test_import_exfat.py

Sans reseau : la fiche est une entree REELLE du flux, relevee le 2026-08-30, et
ses URL sont dechiffrees depuis le fragment, en local.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import import_exfat as E  # noqa: E402

REC = json.loads((ICI / "fixtures" / "exfat_ppsa31246.json").read_text(encoding="utf-8"))

pkg = E.build_package(REC)
assert pkg, "la fiche n'a pas produit de paquet"
groupes = {l["url"]: l.get("group") for l in pkg["downloadLinks"]}
assert groupes, groupes

# La fiche porte le tag « 4.xx BackPork ». La section porte DESORMAIS le
# prefixe exFAT, y compris sur les backports.
#
# DECISION du 2026-08-30, demandee par l'utilisateur. L'attente precedente
# etait l'inverse : « Backport N.xx implique exFAT (621 releves sur 621), le
# prefixer n'apprend rien et fait passer la troncature de 3 % a 23 % ». Deux
# mesures l'ont renversee. Un backport FPKG existe dans le catalogue, donc
# l'implication n'en est pas une. Et la SOURCE vaut verification : sur les
# 1932 backports issus de `.exFAT/exFAT.json` dont le nom a ete releve chez
# l'hebergeur, 1589 disent exFAT, 343 se taisent, AUCUN ne dit PKG. Retirer
# le prefixe privait 585 liens d'une mention exacte.
#
# L'arbitrage d'AFFICHAGE vit ailleurs : pegasus_finalize efface exFAT sur un
# BP sous le seuil correctif, ou la taille en dit plus. La donnee porte la
# verite, l'etiquette choisit ce qu'elle en montre.
for url, g in groupes.items():
    assert g and "Backport" in g, (url, g)
    assert g.startswith("exFAT"), (url, g)

# Temoin negatif : une fiche sans tag de variante reste « exFAT » tout court,
# on n'invente pas de Backport.
sans_tag = dict(REC)
sans_tag["tags"] = ["PPSA31246", "v01.200", "EUR"]
pkg2 = E.build_package(sans_tag)
assert pkg2 and all(l.get("group") == "exFAT" for l in pkg2["downloadLinks"]), \
    [l.get("group") for l in pkg2["downloadLinks"]]

# Temoin negatif : on ne double jamais la mention si la section la porte deja.
deja = dict(REC)
deja["tags"] = ["PPSA31246", "exFAT"]
pkg3 = E.build_package(deja)
for l in pkg3["downloadLinks"]:
    assert l.get("group", "").lower().count("exfat") == 1, l.get("group")

print("OK")
