#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relève le NOM DE FICHIER (et la taille) de chaque lien, chez les hébergeurs
qui acceptent d'être lus sans navigateur.

Pourquoi c'est devenu une étape du pipeline. L'étiquette d'un lien se construit
désormais avec ce que dit le fichier lui-même, pas seulement avec ce que dit la
page source. Mesures du 2026-08-30, sur 8575 noms relevés :

  - DLC : le nom l'affirme 653 fois, l'étiquette 438. 124 liens étaient passés
    de group=DLC à Standard au re-scrape ; 41 des 43 dont on connaît le nom
    disent « DLC » dans le fichier. Le nom rend ce que la source a perdu.
  - Région : 2788 liens la portent dans le nom sans l'avoir dans le champ ; là
    où les deux parlent, ils s'accordent 254 fois sur 257.
  - Numéro de partie : le rang d'affichage « #n » ne valait le vrai numéro que
    45 fois sur 354. Le nom, lui, le donne.
  - Jeu ou correctif : le nom tranche 81 % des cas à 99 % d'exactitude, contre
    60 % pour la taille seule.

Sans cette étape, tout cela retombe au prochain scrape. C'est pour ça qu'elle
est ici et pas dans un script de coin de table.

Hébergeurs couverts, et comment (chacun relevé sur une page réelle) :
  vikingfile / vik1ngfile ... page, <p id="size">, nom dans <title>
  rootz / mediafire ........ nom dans <title> ou dans l'URL
  datanodes / datavaults ... cookie de session obligatoire (404 sans lui)
  filekeeper ............... idem, nom dans id="dl-filename"
  buzzheavier .............. PLUS ICI : passe derriere Cloudflare (403)

Hors de portée ici : akirabox (défi Cloudflare → scripts/lire_akirabox.py via
FlareSolverr) et 1fichier (navigateur → scripts/lire_navigateur.py).

Usage :
  python scripts/relever_noms.py ps5-catalog.json --max 800
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hoster_size as H  # noqa: E402

# Hôtes que `hoster_size.nom_et_taille` sait lire.
HOTES = ("datanodes.to", "filekeeper.net", "datavaults.co")
# buzzheavier EST SORTI le 2026-08-30. Il figurait ici depuis une lecture
# reussie a la main, mais l'hebergeur est passe derriere Cloudflare : les 242
# liens du catalogue rendent tous « HTTP 403 — Just a moment... », 5463 octets
# de defi. Le garder ici ne produisait pas une erreur, il produisait 242
# « echecs » qui ressemblaient a des fichiers supprimes. Sa voie est desormais
# lire_akirabox.py --hotes, qui passe par FlareSolverr.
# Hôtes dont le titre de page porte le nom (lecture directe).
HOTES_TITRE = ("vikingfile.com", "vik1ngfile.site", "rootz.so")

_VERROU = threading.Lock()
_EXT = re.compile(r"(?i)\.(rar|zip|pkg|exfat|7z|iso|bin)(\?|$)")


def _nom_dans_url(url: str):
    """Certains hébergeurs écrivent le nom dans l'URL : c'est gratuit."""
    chemin = unquote(url.split("?")[0])
    if not _EXT.search(chemin):
        return None
    dernier = chemin.rstrip("/").split("/")[-1]
    return dernier if len(dernier) > 6 else None


def _par_titre(url: str):
    """Nom lu dans le <title>, pour les hôtes qui l'y mettent."""
    try:
        code, brut = H._FETCH(url)
    except Exception:                                        # noqa: BLE001
        return (None, None)
    if code != 200:
        return (None, None)
    page = brut.decode("utf-8", "replace")
    m = re.search(r"<title>([^<]{3,140})</title>", page)
    if not m:
        return (None, None)
    titre = m.group(1).strip()
    if not titre or "cloud storage" in titre.lower() or "not found" in titre.lower():
        return (None, None)
    return (titre, H.probe_size(url))


def relever(lien: dict) -> bool:
    """Pose fileName (et sizeBytes si connue). Rend True si quelque chose a été posé."""
    url = lien.get("url") or ""
    nom = _nom_dans_url(url)
    if nom:
        lien["fileName"] = nom
        return True
    hote = H._host(url)
    if hote in HOTES:
        nom, taille = H.nom_et_taille(url)
    elif hote in HOTES_TITRE:
        nom, taille = _par_titre(url)
    else:
        return False
    from releves import ressemble_a_un_nom_de_fichier
    if not ressemble_a_un_nom_de_fichier(nom):
        # « Data Vaults | Free Unlimited Files Upload Services » etait entre par
        # ici : le <title> d'une page d'accueil servie a la place du fichier.
        return False
    lien["fileName"] = nom
    if taille and not lien.get("sizeBytes"):
        lien["sizeBytes"] = taille
    return True


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("--max", type=int, default=0, help="Nombre max de relevés (0 = tout)")
    ap.add_argument("--fils", type=int, default=4)
    ap.add_argument("--releves", type=Path, default=None,
                    help="Ecrire un releve a part au lieu de reecrire le "
                         "catalogue (permet de tourner en parallele d'une autre "
                         "collecte ; voir scripts/releves.py)")
    args = ap.parse_args(argv)

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    cibles = [l for pkg in data.get("packages", [])
              for l in (pkg.get("downloadLinks") or [])
              if not l.get("fileName")
              and (H._host(l.get("url", "")) in HOTES + HOTES_TITRE
                   or _nom_dans_url(l.get("url", "")))]
    if args.max:
        cibles = cibles[:args.max]
    print(f"{len(cibles)} lien(s) à relever", flush=True)
    if not cibles:
        return 0

    compte = {"poses": 0, "echecs": 0}

    def _un(lien):
        time.sleep(random.random() * 0.4)
        ok = False
        try:
            ok = relever(lien)
        except Exception:                                    # noqa: BLE001
            ok = False
        with _VERROU:
            compte["poses" if ok else "echecs"] += 1
            n = compte["poses"] + compte["echecs"]
            if n % 200 == 0:
                print(f"  {n}/{len(cibles)} — {compte['poses']} noms", flush=True)

    with ThreadPoolExecutor(max_workers=args.fils) as ex:
        list(ex.map(_un, cibles))

    if args.releves:
        import releves
        n = releves.ecrire(args.releves, cibles)
        print(f"{n} releve(s) ecrit(s) dans {args.releves}"
              " — le catalogue n est PAS touche ici")
    else:
        args.catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    print(f"{compte['poses']} nom(s) posé(s), {compte['echecs']} échec(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
