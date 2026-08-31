#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relevés de noms de fichiers : écriture à part, application groupée.

POURQUOI ce détour plutôt qu'une écriture directe. Trois étapes du pipeline
posent `fileName` sur des liens — `relever_noms.py` (hébergeurs lisibles),
`lire_akirabox.py` (via FlareSolverr), `lire_navigateur.py` (1fichier). Elles
touchent des hôtes DISJOINTS, donc rien ne les empêche de tourner en même
temps… sauf qu'elles réécrivaient toutes `ps5-catalog.json` en entier. Deux
d'entre elles lancées ensemble et le dernier qui ferme le fichier efface le
travail de l'autre — silencieusement, sans erreur, avec un catalogue
parfaitement valide à l'arrivée. C'est exactement la panne qui ne se voit pas.

Chacune écrit donc son propre relevé — `{url: {fileName, sizeBytes}}` — et une
étape d'application les verse tous dans le catalogue. L'application est
séquentielle et instantanée ; c'est la COLLECTE, qui attend le réseau, qui
gagne à être parallèle.

Un champ déjà posé n'est jamais écrasé : le catalogue a toujours raison contre
un relevé, qui peut dater d'un run précédent réappliqué par mégarde.

Usage :
  python scripts/releves.py ps5-catalog.json releve-lisibles.json releve-akirabox.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CHAMPS = ("fileName", "sizeBytes", "linkDead")

# Un nom de fichier porte une extension, ou l'identifiant Sony du jeu. Un titre
# de site n'a ni l'un ni l'autre.
_EXT = re.compile(r"(?i)[.][a-z0-9]{2,6}\s*$")
# datavaults sert « PPSA14396 exfat » : le point est remplace par une espace.
_EXT_ESPACE = re.compile(r"(?i)[ _-](rar|zip|7z|pkg|fpkg|ffpkg|exfat|iso|bin|ps5)\s*$")
_ID_SONY = re.compile(r"(?i)(ppsa|cusa|ppsf|nppa)[ _-]?[0-9]{4,}")


def ressemble_a_un_nom_de_fichier(nom) -> bool:
    """Garde-fou avant d'ecrire fileName. Voir test_nom_plausible.py.

    Le 2026-08-30, la sonde gofile a ecrit « Content not found · Gofile » dans
    fileName sur 61 liens : le parseur prend og:title, et ce cas acceptait
    n'importe quel texte. Un parseur qui n'a jamais vu un gabarit ne rend pas
    « erreur », il rend un resultat PLAUSIBLE — et ce nom serait ensuite passe
    dans marques_du_nom et region_du_nom pour etiqueter les liens.

    Ce garde ne cherche PAS des mots d'erreur : une premiere version rejetait
    « PPSA14404.exfat » parce que le titleId contient 404, et un fichier de
    « Quantum Error » parce que le jeu s'appelle ainsi. Il cherche la marque
    POSITIVE d'un fichier. Mesure sur les 10630 noms deja releves : 71 rejets,
    0,67 %, dont 70 sont de vrais titres de site.
    """
    if not nom:
        return False
    return bool(_EXT.search(nom) or _EXT_ESPACE.search(nom) or _ID_SONY.search(nom))



def ecrire(chemin, liens) -> int:
    """Dépose {url: {champs}} pour les liens qui ont reçu un nom. Rend le compte."""
    # Un lien MORT est un releve aussi : c'est meme le plus utile, puisqu'il
    # evite de le resonder a chaque run. Ne retenir que les liens NOMMES le
    # perdait en route.
    releve = {l["url"]: {k: l[k] for k in CHAMPS if l.get(k)}
              for l in liens if l.get("url")
              and (ressemble_a_un_nom_de_fichier(l.get("fileName"))
                   or l.get("linkDead"))}
    Path(chemin).write_text(json.dumps(releve, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    return len(releve)


def appliquer(catalogue: dict, releves: dict) -> int:
    """Verse les relevés dans le catalogue (en place). Rend le nombre de champs posés.

    Applique à TOUTES les occurrences de l'URL : le même lien peut figurer sur
    plusieurs fiches (miroir partagé), et il n'y a aucune raison de n'en nommer
    qu'une.
    """
    par_url: dict = {}
    for pkg in catalogue.get("packages", []):
        for lien in pkg.get("downloadLinks") or []:
            if lien.get("url"):
                par_url.setdefault(lien["url"], []).append(lien)
    poses = 0
    for url, champs in releves.items():
        for lien in par_url.get(url, ()):
            for cle, valeur in champs.items():
                if valeur and not lien.get(cle):
                    lien[cle] = valeur
                    poses += 1
    return poses


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("releves", type=Path, nargs="+")
    args = ap.parse_args(argv)

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    total = 0
    for chemin in args.releves:
        if not chemin.exists():
            print(f"  {chemin} : absent, ignore")
            continue
        r = json.loads(chemin.read_text(encoding="utf-8"))
        n = appliquer(data, r)
        total += n
        print(f"  {chemin} : {len(r)} releve(s) -> {n} champ(s) pose(s)")
    args.catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(f"{total} champ(s) pose(s) dans {args.catalog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
