#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remplace un lien LinkVault par les liens reels qu il agrege.

POURQUOI. `link-vault.org/c/<slug>` n heberge RIEN : c est une page qui agrege
les miroirs d un meme paquet. Pour « DOOM Eternal », un seul conteneur porte 32
liens — 8 parties x Gofile, Vikingfile, 1Fichier, Rootz — chacun avec son nom
de fichier complet, sa taille et son etat de disponibilite audite la veille.
Nommer la page intermediaire n apportait presque rien ; la resoudre apporte les
fichiers.

MESURE du 2026-08-30 : les 8 liens Gofile du conteneur DOOM Eternal sont
ABSENTS du catalogue. Le conteneur apporte du contenu NEUF. Sur 40 conteneurs
releves : 453 liens, aucun desaccord entre le nombre de noms affiches et le
nombre d URL exportees.

COMMENT LE RELEVE EST OBTENU, et pourquoi il n est pas dans ce script. Les URL
ne sont NI dans le HTML rendu (zero occurrence de « gofile.io/d/ » sur 83 Ko),
NI accessibles sans le bouton « Export All » de la page, qui ecrit dans le
presse-papier. Elles ne transitent autrement que par une API protegee par un
jeton Turnstile — fabriquer ces jetons en serie serait contourner une
protection anti-bot, et ce n est pas fait. Le releve se fait donc au navigateur,
en se servant du bouton que le site propose, et ce script ingere son resultat.

Format attendu (JSON) :
  {"<slug>": {"titre": "...", "hotes": {"Gofile": [{"url":…,"nom":…,"taille":"10 GB"}]}}}

Usage :
  python scripts/ingerer_linkvault.py ps5-catalog.json lv-a.json lv-b.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_FACTEURS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
_RE_TAILLE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([KMGT]?B)\s*$", re.I)


def taille_en_octets(texte):
    """« 10 GB », « 8.58 GB », « 169.09 MB » -> octets. None si ce n en est pas une."""
    m = _RE_TAILLE.match(texte or "")
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", ".")) * _FACTEURS[m.group(2).upper()])
    except (ValueError, KeyError):
        return None


def ingerer(catalogue: dict, releve: dict) -> dict:
    """Remplace chaque lien LinkVault resolu par les liens qu il agrege.

    Le conteneur est RETIRE une fois resolu : il ne menait a aucun fichier. Les
    nouveaux liens heritent de sa section et de sa version — ce que la page
    source disait du paquet reste vrai des fichiers qu il contient.

    Un hote en « desaccord » (le nombre d URL exportees ne colle pas au nombre
    de noms affiches) est IGNORE : apparier au hasard poserait des noms faux sur
    des URL justes, ce qui est pire que pas de nom du tout.
    """
    stats = {"ajoutes": 0, "conteneurs_resolus": 0, "hotes_ignores": 0}
    for pkg in catalogue.get("packages", []):
        liens = pkg.get("downloadLinks") or []
        connues = {(l.get("url") or "") for l in liens}
        gardes, ajouts = [], []
        for lien in liens:
            url = lien.get("url") or ""
            if "link-vault.org" not in url:
                gardes.append(lien)
                continue
            slug = url.rstrip("/").split("/")[-1]
            bloc = releve.get(slug)
            if not bloc or not bloc.get("hotes"):
                gardes.append(lien)              # pas de releve : on ne touche pas
                continue
            neufs = 0
            for hote, lot in bloc["hotes"].items():
                if not isinstance(lot, list):
                    stats["hotes_ignores"] += 1
                    continue
                for e in lot:
                    u = (e.get("url") or "").strip()
                    if not u or u in connues:
                        continue
                    connues.add(u)
                    neuf = {"url": u, "name": hote, "mirror": hote}
                    if e.get("nom"):
                        neuf["fileName"] = e["nom"]
                    octets = taille_en_octets(e.get("taille"))
                    if octets:
                        neuf["sizeBytes"] = octets
                    # LinkVault audite ses liens et affiche « Available ». C'est
                    # la SEULE source du catalogue qui sache dire si un lien
                    # 1fichier est vivant : cet hote ne se sonde pas autrement.
                    # Un etat ABSENT ne vaut pas « mort » — l'absence
                    # d'information n'est pas une information, et la traiter
                    # comme telle ferait disparaitre des liens vivants.
                    etat = (e.get("etat") or "").strip().lower()
                    if etat and etat not in ("available", "disponible"):
                        neuf["linkDead"] = True
                    for champ in ("group", "version", "region", "editionId"):
                        if lien.get(champ):
                            neuf[champ] = lien[champ]
                    ajouts.append(neuf)
                    neufs += 1
            if neufs:
                stats["ajoutes"] += neufs
                stats["conteneurs_resolus"] += 1   # le conteneur disparait
            else:
                gardes.append(lien)                # rien de neuf : on le garde
        pkg["downloadLinks"] = gardes + ajouts
    return stats


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("releves", type=Path, nargs="+")
    args = ap.parse_args(argv)

    releve = {}
    for chemin in args.releves:
        if not chemin.exists():
            print(f"  {chemin} : absent, ignore")
            continue
        d = json.loads(chemin.read_text(encoding="utf-8"))
        releve.update({k: v for k, v in d.items() if isinstance(v, dict) and v.get("hotes")})
        print(f"  {chemin} : {len(d)} conteneur(s)")
    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    avant = sum(len(p.get("downloadLinks") or []) for p in data.get("packages", []))
    stats = ingerer(data, releve)
    apres = sum(len(p.get("downloadLinks") or []) for p in data.get("packages", []))
    args.catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{stats['conteneurs_resolus']} conteneur(s) resolu(s), "
          f"{stats['ajoutes']} lien(s) ajoute(s), "
          f"{stats['hotes_ignores']} hote(s) ignore(s) pour desaccord")
    print(f"liens : {avant} -> {apres}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
