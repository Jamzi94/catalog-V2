#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La sonde de taille vikingfile, sur une page REELLE.

    python scripts/test_hoster_size.py

vikingfile est le premier hebergeur du catalogue (3623 liens) et la sonde
rendait None sur TOUS : elle interrogeait une API du domaine .com alors que le
site a bascule sur vik1ngfile.site. Un instrument qui rend None ne dit pas
« insondable », il dit « je n'ai pas su regarder » — et le lien etait classe
insondable.
"""
from __future__ import annotations

import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hoster_size as H  # noqa: E402

PAGE = (ICI / "fixtures" / "vikingfile_page.html").read_text(encoding="utf-8")

import json
import tempfile

# Cache ISOLE : sans ca le test lirait le cache du depot, ou dorment des None
# ecrits par la sonde aveugle — on mesurerait le fossile.
_tmp = tempfile.TemporaryDirectory()
H.CACHE_DIR = Path(_tmp.name)

appels = []


def _faux_fetch(url, *, method="GET", data=None, headers=None, timeout=None):
    appels.append(url)
    return 200, PAGE.encode("utf-8")


H.set_fetcher(_faux_fetch)

# La page annonce « 121.09 GB » dans <p id="size">.
taille = H.probe_size("https://vik1ngfile.site/f/BHQuBFHoGm")
assert taille is not None, "sonde aveugle sur le nouveau domaine"
en_go = taille / 1024 ** 3
assert 120.5 < en_go < 121.5, (taille, en_go)

# Le domaine historique redirige : il doit marcher aussi.
assert H.probe_size("https://vikingfile.com/f/BHQuBFHoGm") is not None

# TEMOIN NEGATIF — la page porte, dans son script obfusque et ses encarts, des
# « 70KB », « 4MB » et « 20GB » qui ne sont PAS la taille du fichier. Une sonde
# qui attrape le premier nombre venu rendrait une taille plausible et fausse.
assert not (0 < taille < 100 * 1024 ** 2), f"taille suspecte : {taille}"
assert abs(taille - 20 * 1024 ** 3) > 1024 ** 3, "la sonde a pris le « 20GB » de l'encart"

# TEMOIN NEGATIF — sans le bloc, on rend None, pas un chiffre invente.
H.set_fetcher(lambda url, **k: (200, b"<html><body>rien ici</body></html>"))
assert H.probe_size("https://vik1ngfile.site/f/AUTRE") is None

# TEMOIN — une entree ecrite par une sonde ANTERIEURE ne doit pas resservir :
# son None peut venir d'un instrument aveugle, pas d'un fichier insondable.
# C'est exactement ce qui aurait rendu ce correctif inerte sur 3623 liens.
import hashlib
url = "https://vik1ngfile.site/f/FOSSILE"
f = H.CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")
f.write_text(json.dumps({"url": url, "size": None, "sonde": H.SONDE_VERSION - 1}))
H.set_fetcher(_faux_fetch)
assert H.probe_size(url) is not None, "le None fossile a resservi"

# ... mais un None ecrit par la sonde COURANTE ressert, sinon on re-sonderait
# a chaque run des fichiers reellement insondables.
url2 = "https://vik1ngfile.site/f/INSONDABLE"
f2 = H.CACHE_DIR / (hashlib.sha256(url2.encode()).hexdigest()[:20] + ".json")
f2.write_text(json.dumps({"url": url2, "size": None, "sonde": H.SONDE_VERSION}))
appels.clear()
assert H.probe_size(url2) is None and not appels, "re-sondage inutile"

print("OK")
