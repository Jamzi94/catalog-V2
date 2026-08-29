#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le format ecrit sur la ligne « Version » doit atteindre les liens.

    python scripts/test_scrape_superpsx.py

Sans reseau : parse_dll_page lit d'abord son cache disque, on l'amorce donc
avec une table REELLE, relevee le 2026-08-29 sur superpsx.com/dll-re9r/
(Resident Evil Requiem). Le lien Viki de cette table pointe sur un fichier
nomme PPSA31246.exfat, et il sortait etiquete « PKG ».
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import scrape_superpsx as S  # noqa: E402

TABLE = (ICI / "fixtures" / "superpsx_table_exfat.html").read_text(encoding="utf-8")
PAGE = "<html><body>{}</body></html>"


def _rubriques(table_html: str) -> dict:
    """Rend {url: group} pour une page batie autour de cette table."""
    faux_url = "https://exemple.invalide/dll-test-" + str(abs(hash(table_html)) % 10**8)
    S._cache_set(faux_url, PAGE.format(table_html))
    res = S.parse_dll_page(faux_url)
    assert res, "la page n'a pas ete parsee"
    return {l["url"]: l.get("group") for l in res["links"]}


with tempfile.TemporaryDirectory() as tmp:
    S.DISK_CACHE_DIR = Path(tmp)          # cache isole, jamais celui du depot

    VIKI = "https://vikingfile.com/f/BHQuBFHoGm"

    # La table reelle : « Version ⇛ PPSA31246 – EUR (exFAT) » puis
    # « Game (v01.200.000) ⇛ <liens> ». La rubrique ne dit rien du format.
    assert _rubriques(TABLE)[VIKI] == "exFAT", _rubriques(TABLE)

    # Temoin negatif : sans la mention sur la ligne Version, rien n'est invente.
    sans = TABLE.replace(" (exFAT)", "")
    assert " (exFAT)" not in sans and "BHQuBFHoGm" in sans
    assert _rubriques(sans)[VIKI] == "Standard", _rubriques(sans)

    # Temoin negatif : une rubrique explicite reste prioritaire, elle est plus
    # proche des liens que l'en-tete de table.
    backport = TABLE.replace("Game (v01.200.000) ⇛", "Game (v01.200.000) (Backport) ⇛")
    assert _rubriques(backport)[VIKI] == "Backport", _rubriques(backport)

# --- T2 : une rubrique inconnue ne doit plus disparaitre en silence --------
# detect_section est un vocabulaire FERME de neuf regex tenues a la main. Le
# jour ou le site renomme « Backport » en « FW Bypass », la ligne entiere est
# ignoree, ses liens ne sont JAMAIS extraits, et le run se termine en succes.
# 3007 liens Backport dependent aujourd'hui de ce vocabulaire.
INCONNUE = TABLE.replace(
    "<strong>Game (v01.200.000) ⇛</strong>",
    "<strong>FW Bypass Machin ⇛</strong>")
assert "FW Bypass" in INCONNUE

faux = "https://exemple.invalide/dll-inconnue"
S._cache_set(faux, PAGE.format(INCONNUE))
res = S.parse_dll_page(faux)
assert res, "page non parsee"
assert res.get("rubriques_non_reconnues"), res.get("rubriques_non_reconnues")
assert any("FW Bypass" in x for x in res["rubriques_non_reconnues"]), res["rubriques_non_reconnues"]

# Temoin negatif : la table d'origine, dont toutes les rubriques sont connues,
# ne doit RIEN signaler. Sans lui, un compteur qui crie tout le temps ne vaut
# pas mieux qu'un compteur muet.
faux2 = "https://exemple.invalide/dll-connue"
S._cache_set(faux2, PAGE.format(TABLE))
res2 = S.parse_dll_page(faux2)
assert not res2.get("rubriques_non_reconnues"), res2.get("rubriques_non_reconnues")

print("OK")
