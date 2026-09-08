#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le numero de partie passe EN TETE, et le format complet revient.

DEUX DEMANDES du 2026-09-08, apres essai du rendu par l utilisateur.

1. LE NUMERO DE PARTIE ETAIT PERDU. Il s ecrivait APRES le crochet fermant,
   donc en fin de ligne — la ou l ellipse coupe. Mesure sur les 1904 liens en
   plusieurs morceaux : 1029, soit 54 %, perdaient leur numero a l ecran.

       [GAME PKG APR-EMU 10 Go USA] 01/12
                                      ^ visible jusqu ici, « /12 » coupe

   Or c est l information la plus critique d une archive decoupee : il faut la
   TOTALITE des morceaux, et un manquant doit se voir.

2. LE FORMAT DOIT ETRE VISIBLE EN ENTIER. J avais masque « Folder », « FFPFSC »
   et « FFPKG » au motif qu ils etaient redondants avec PKG — 2962 liens
   concernes. L utilisateur les veut : ils disent ce qu on va manipuler.

Cout assume et mesure : la troncature passe de 9 % a 13 %. Ce qui sort du cadre
est la version en queue, jamais le format ni le numero.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import finalize_package                        # noqa: E402

Go = 1024 ** 3


def _etiq(liens, version="01.000"):
    pkg = {"titleId": "PPSA00001", "title": "Jeu", "version": version,
           "downloadLinks": [dict({"name": "V"}, **l) for l in liens]}
    finalize_package(pkg, {})
    return [l.get("name") for l in pkg["downloadLinks"]]


# --- le numero est DANS les crochets, en tete -------------------------------
n = _etiq([{"url": f"https://v/jeu.part0{i}.rar", "group": "PKG",
            "sizeBytes": 10 * Go, "fileName": f"jeu.part0{i}.rar"} for i in (1, 2, 3)])
for i, x in enumerate(n, 1):
    assert x.startswith(f"[{i:02d}/03 "), x
# TEMOIN : il precede meme le role — un morceau manquant se voit avant tout.
assert n[0] == "[01/03 GAME PKG 10 Go]", n

# --- le rang d affichage « #n » passe aussi en tete --------------------------
# Le rang ne s applique qu a des liens de MEME libelle ET MEME hote : c est la
# que l app les montre comme des doublons. Deux hotes differents se distinguent
# deja par la ligne d hote affichee dessous.
n = _etiq([{"url": "https://a.com/x", "group": "PKG", "sizeBytes": 5 * Go},
           {"url": "https://a.com/y", "group": "PKG", "sizeBytes": 5 * Go}])
assert all(x.startswith("[#0") for x in n), n

# --- le format COMPLET revient ----------------------------------------------
n = _etiq([{"url": "https://v/1", "group": "PKG · Folder · FFPFSC",
            "sizeBytes": 66 * Go, "fileName": "jeu.pkg"}])
for mot in ("PKG", "Folder", "FFPFSC"):
    assert mot in n[0], (mot, n)

# --- TEMOIN : un lien unique n a NI numero NI rang --------------------------
n = _etiq([{"url": "https://v/seul", "group": "exFAT", "sizeBytes": 40 * Go,
            "fileName": "PPSA1.exfat"}])
assert n[0] == "[GAME exFAT 40 Go]", n

print("OK")
