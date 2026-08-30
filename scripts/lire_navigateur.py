#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relevé du nom de fichier et de la taille chez les hébergeurs qui exigent un
navigateur — aujourd'hui 1fichier.

Pourquoi un navigateur. 1fichier n'expose AUCUNE API anonyme : tous les
endpoints documentés (`/file/info.cgi`, `/file/ls.cgi`…) réclament une clé, donc
un compte. Et une requête nue sur la page d'un fichier ne rend qu'un mur de
consentement de 12 Ko — vérifié le 2026-08-30 avec plusieurs jeux d'en-têtes et
un cookie de consentement forgé, sans succès. Chargée dans un navigateur, la
même page porte, dans une cellule de tableau, « <nom du fichier> <taille> ».

Le découpage de cette cellule vit dans `decouper_cellule`, fonction pure et
testée hors ligne : c'est la seule partie qu'on puisse tenir sans réseau. Le
reste — lancer le navigateur, attendre le rendu — ne se prouve que sur l'objet
réel, et le script le fait bruyamment (compteur d'échecs).

Ne traite PAS akirabox : ses pages sont derrière un défi Cloudflare qui résiste
au navigateur, headless comme visible (« Vérification de sécurité en cours »,
HTTP 403). La voie pour lui est FlareSolverr, déjà outillé dans ce dépôt via
`flaresolverr_pool.py`.

Usage :
  python scripts/lire_navigateur.py ps5-catalog.json --max 300
  python scripts/lire_navigateur.py ps5-catalog.json --max 300 --seulement-bp
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# « nom  12.5 Go » — la taille est en fin de cellule, unités françaises.
_RE_TAILLE_FIN = re.compile(r"^(.*?)\s+([\d.,]+)\s*(Ko|Mo|Go|To|KB|MB|GB|TB)\s*$", re.I)
_FACTEURS = {"KO": 1024, "MO": 1024 ** 2, "GO": 1024 ** 3, "TO": 1024 ** 4,
             "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}


def decouper_cellule(cellule) -> tuple:
    """(nom, octets) à partir de la cellule « nom  taille » de 1fichier.

    Rend (nom, None) si la cellule ne porte pas de taille, et (None, None) si
    elle est vide : on n'invente pas un chiffre pour faire nombre.
    """
    texte = re.sub(r"\s+", " ", (cellule or "")).strip()
    if not texte:
        return (None, None)
    m = _RE_TAILLE_FIN.match(texte)
    if not m:
        return (texte, None)
    nombre = m.group(2).replace(",", ".")
    try:
        octets = int(float(nombre) * _FACTEURS[m.group(3).upper()])
    except (ValueError, KeyError):
        return (texte, None)
    return (m.group(1).strip(), octets)


def _lire_pages(urls: list, entete: str = 'table[cellspacing="4"] td') -> dict:
    """Ouvre chaque URL dans un navigateur et rend {url: (nom, octets)}."""
    from playwright.sync_api import sync_playwright

    resultats: dict = {}
    with sync_playwright() as p:
        navigateur = p.chromium.launch(headless=True)
        page = navigateur.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        for i, url in enumerate(urls, 1):
            try:
                page.goto(url, timeout=35000, wait_until="domcontentloaded")
                page.wait_for_timeout(700)
                cellule = page.locator(entete).nth(1).inner_text(timeout=5000)
                resultats[url] = decouper_cellule(cellule)
            except Exception:                                # noqa: BLE001
                resultats[url] = (None, None)
            if i % 50 == 0:
                trouves = sum(1 for v in resultats.values() if v[0])
                print(f"  {i}/{len(urls)} — {trouves} noms relevés", flush=True)
        navigateur.close()
    return resultats


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("--max", type=int, default=0, help="Nombre max de pages (0 = tout)")
    ap.add_argument("--hote", default="1fichier.com")
    ap.add_argument("--seulement-bp", action="store_true",
                    help="Se limiter aux liens dont l'étiquette porte « BP »")
    args = ap.parse_args(argv)

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    cibles = []
    for pkg in data.get("packages", []):
        for lien in pkg.get("downloadLinks") or []:
            if args.hote not in lien.get("url", ""):
                continue
            if lien.get("fileName"):
                continue
            if args.seulement_bp and "BP" not in (lien.get("name") or ""):
                continue
            cibles.append(lien)
    if args.max:
        cibles = cibles[:args.max]
    print(f"{len(cibles)} page(s) à lire chez {args.hote}", flush=True)
    if not cibles:
        return 0

    resultats = _lire_pages([l["url"] for l in cibles])
    noms = tailles = 0
    for lien in cibles:
        nom, octets = resultats.get(lien["url"], (None, None))
        if nom:
            lien["fileName"] = nom
            noms += 1
        if octets:
            lien["sizeBytes"] = octets
            tailles += 1
    args.catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{noms} nom(s), {tailles} taille(s) — {len(cibles) - noms} échec(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
