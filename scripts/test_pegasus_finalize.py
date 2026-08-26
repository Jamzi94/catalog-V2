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
from pegasus_finalize import _clean_links, _number_parts  # noqa: E402


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

print("OK")
