#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un changement de PARSEUR doit invalider les paquets mis en cache.

    python scripts/test_scrape_manifest.py

Le manifeste met en cache le PAQUET DEJA ANALYSE, pas le HTML : tant que le
content_hash d'une page ne bouge pas, aucun correctif de parseur ne l'atteint.
Mesure du 2026-08-30 : 1139 entrees, 1139 paquets en cache, 4091 liens — les
correctifs poses les 29 et 30 aout y sont inertes.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape_manifest as M  # noqa: E402

URL = "https://exemple.invalide/jeu/"


def _ecrire(tmp: Path, parser_version) -> Path:
    p = tmp / "manifeste.json"
    data = {
        "version": M.MANIFEST_VERSION,
        "updated_at": "2026-08-30T00:00:00+00:00",
        "last_run": "2026-08-30T00:00:00+00:00",
        "entries": {URL: {"content_hash": "abc", "last_seen": "2026-08-30T00:00:00+00:00",
                          "package": {"titleId": "PPSA00001", "downloadLinks": []}}},
    }
    if parser_version is not None:
        data["parser_version"] = parser_version
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)

    # Meme version de parseur : le paquet en cache est reutilise (c'est tout
    # l'interet de l'incremental, on ne casse pas ca).
    m = M.ScrapeManifest(_ecrire(tmp, M.PARSER_VERSION))
    assert m.get_cached_package(URL) is not None, "le cache devrait resservir"

    # Version differente : le paquet est LARGUE, la page sera re-analysee.
    m = M.ScrapeManifest(_ecrire(tmp, M.PARSER_VERSION - 1))
    assert m.get_cached_package(URL) is None, "le paquet fossile a resservi"

    # ... mais l'entree survit : on ne perd ni le content_hash ni last_seen,
    # sinon on transformerait chaque bump de parseur en re-scrape total du site.
    assert URL in m.list_entries_urls(), "l'entree a ete jetee avec l'eau du bain"

    # Manifeste ancien, sans la cle : on ne peut pas savoir avec quel parseur il
    # a ete ecrit, donc on largue aussi. Le doute ne profite pas au cache.
    m = M.ScrapeManifest(_ecrire(tmp, None))
    assert m.get_cached_package(URL) is None, "un manifeste sans version a resservi"

print("OK")
