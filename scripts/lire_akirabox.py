#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relevé du nom et de la taille chez akirabox, à travers FlareSolverr.

Pourquoi FlareSolverr. Akirabox est le PREMIER hébergeur du catalogue par le
nombre de liens (2 903, dont 2 904 sans nom relevé) et le seul qui résiste à
tout ce qui a marché ailleurs, mesuré le 2026-08-30 :

  requête nue, en-têtes de navigateur complets ...... HTTP 403
  cookie de session (méthode datanodes/filekeeper) .. HTTP 403
  navigateur headless (Playwright) ................. « Un instant… », 403
  navigateur VISIBLE ............................... idem
  lecteur tiers (r.jina.ai) ........................ renvoie le défi

Le point commun : `akirabox.com` redirige vers `akirabox.to`, protégé par un
défi Cloudflare que seul un vrai navigateur *non instrumenté* franchit. C'est
exactement ce que résout FlareSolverr, que la CI fait déjà tourner en cinq
instances pour SuperPSX (`flaresolverr_pool.py`).

Ce module ne s'exécute donc utilement qu'en CI, ou en local si l'on renseigne
`FLARESOLVERR_URLS`. La partie qui compte — l'ANALYSE de la page — est une
fonction pure, `extraire_nom_taille`, testable hors ligne dès qu'on dispose
d'une page d'exemple.

Usage :
  FLARESOLVERR_URLS=http://localhost:8191/v1 \
      python scripts/lire_akirabox.py ps5-catalog.json --max 200
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_FACTEURS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4,
             "KO": 1024, "MO": 1024 ** 2, "GO": 1024 ** 3, "TO": 1024 ** 4}


def _octets(nombre: str, unite: str):
    try:
        return int(float(nombre.replace(",", ".")) * _FACTEURS[unite.upper().replace("I", "")])
    except (ValueError, KeyError):
        return None


def extraire_nom_taille(page: str) -> tuple:
    """(nom, octets) depuis le HTML d'une page akirabox, sinon (None, None).

    On essaie, dans l'ordre, les ancres qui ont servi chez les quatre autres
    hébergeurs — elles couvrent les gabarits courants :

      1. <meta property="og:title" content="NOM (12.3 GB)">   (datanodes)
      2. <title>NOM</title>                                    (buzzheavier)
      3. <input name="fname" value="NOM">                      (datavaults)
      4. id="dl-filename"                                      (filekeeper)

    Puis la taille au voisinage immédiat du nom, jamais ailleurs : les pages
    d'hébergeurs affichent toutes des tailles d'encart (limites d'offre,
    quotas), et les prendre pour la taille du fichier donne un chiffre
    plausible et faux — c'est le piège qui a été rencontré chez datavaults,
    dont la page n'annonce AUCUNE taille de fichier.

    Cette fonction est écrite d'après les gabarits connus et n'a PAS encore été
    confrontée à une vraie page akirabox : tant que ce n'est pas fait, son
    résultat est [NM]. Le test l'accompagnera dès qu'une capture existera.
    """
    if not page:
        return (None, None)

    # 1) og:title « nom (taille) »
    marque = "og:title" + chr(34) + " content=" + chr(34)
    i = page.find(marque)
    if i >= 0:
        j = page.find(chr(34), i + len(marque))
        og = page[i + len(marque):j] if j > 0 else ""
        m = re.match(r"^(.*?)[ ]*\(([0-9.,]+)[ ]*([KMGT]?i?B|[KMGT]?o)\)[ ]*$", og)
        if m:
            return (m.group(1).strip(), _octets(m.group(2), m.group(3)))
        if og:
            return (og.strip(), _taille_pres_de(page, i))

    # 2) champ caché « fname » (gabarit XFileSharing)
    marque = "name=" + chr(34) + "fname" + chr(34) + " value=" + chr(34)
    i = page.find(marque)
    if i >= 0:
        j = page.find(chr(34), i + len(marque))
        nom = page[i + len(marque):j] if j > 0 else ""
        if nom:
            return (nom, _taille_pres_de(page, i))

    # 3) id="dl-filename"
    marque = "id=" + chr(34) + "dl-filename" + chr(34)
    i = page.find(marque)
    if i >= 0:
        j, k = page.find(">", i), page.find("<", page.find(">", i) + 1)
        nom = page[j + 1:k].strip() if j > 0 and k > j else ""
        if nom:
            return (nom, _taille_pres_de(page, i))

    # 4) le titre, s'il ressemble à un nom de fichier et pas au nom du site
    m = re.search(r"<title>([^<]{3,140})</title>", page)
    if m:
        titre = m.group(1).strip()
        if "akirabox" not in titre.lower() and re.search(r"\.[a-z0-9]{2,5}$", titre, re.I):
            return (titre, _taille_pres_de(page, m.start()))
    return (None, None)


def _taille_pres_de(page: str, position: int):
    """Première taille rencontrée APRÈS le nom, dans une fenêtre courte.

    Fenêtre volontairement étroite : plus loin dans la page dorment les tailles
    d'encart (« Max upload 1 GB », « Storage 15 GB ») qu'il ne faut surtout pas
    servir comme taille du fichier.
    """
    m = re.search(r"([0-9][0-9.,]*) *([KMGT]i?B|[KMGT]o)", page[position:position + 4000])
    return _octets(m.group(1), m.group(2)) if m else None


def _pool():
    from flaresolverr_pool import FlareSolverrPool, parse_flaresolverr_urls
    urls = parse_flaresolverr_urls()
    if not urls:
        return None
    return FlareSolverrPool(urls)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("--max", type=int, default=0)
    args = ap.parse_args(argv)

    pool = _pool()
    if pool is None:
        print("FLARESOLVERR_URLS non renseigné — rien à faire ici. "
              "Ce script s'exécute en CI, où cinq instances tournent.")
        return 0

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    cibles = [l for pkg in data.get("packages", [])
              for l in (pkg.get("downloadLinks") or [])
              if "akirabox" in l.get("url", "") and not l.get("fileName")]
    if args.max:
        cibles = cibles[:args.max]
    print(f"{len(cibles)} page(s) akirabox à lire", flush=True)

    noms = tailles = echecs = 0
    for i, lien in enumerate(cibles, 1):
        try:
            reponse = pool.get(lien["url"])
            nom, octets = extraire_nom_taille(getattr(reponse, "text", "") or "")
        except Exception:                                    # noqa: BLE001
            nom, octets = None, None
        if nom:
            lien["fileName"] = nom
            noms += 1
            if octets:
                lien["sizeBytes"] = octets
                tailles += 1
        else:
            echecs += 1
        if i % 50 == 0:
            print(f"  {i}/{len(cibles)} — {noms} noms, {echecs} échecs", flush=True)
    args.catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{noms} nom(s), {tailles} taille(s), {echecs} échec(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
