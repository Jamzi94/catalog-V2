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
# 1fichier a son propre gabarit — voir _lire_1fichier. Il est LISIBLE en
# requete simple, contrairement a ce que laissait croire lire_navigateur.py.
HOTES_DEDIES = ("1fichier.com",)

_VERROU = threading.Lock()
_EXT = re.compile(r"(?i)\.(rar|zip|pkg|exfat|7z|iso|bin)(\?|$)")


def _nom_dans_url(url: str):
    """Certains hébergeurs écrivent le nom dans l'URL : c'est gratuit."""
    chemin = unquote(url.split("?")[0])
    if not _EXT.search(chemin):
        return None
    dernier = chemin.rstrip("/").split("/")[-1]
    return dernier if len(dernier) > 6 else None


_FACTEURS_1F = {"O": 1, "KO": 1024, "MO": 1024 ** 2, "GO": 1024 ** 3, "TO": 1024 ** 4,
                "B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
_RE_1F_NOM = re.compile('class="tier-name"[^>]*>([^<]{3,180})<')
_RE_1F_TAILLE = re.compile('class="tier-feat"[^>]*>[ ]*([0-9][0-9.,]*)[ ]*([KMGT]?[OB])[ ]*<', re.I)


def _lire_1fichier(page):
    """(nom, octets) depuis une page 1fichier. Gabarit releve le 2026-09-01 :

        <span class="tier-name">[DLPSGAME.COM] - 02.004 PPSA09482.rar</span>
        <span class="tier-feat">32.49 Go</span>

    Ni navigateur ni cookie : une requete HTTP avec un en-tete de navigateur
    suffit. lire_navigateur.py, ecrit pour cet hote, rendait 0 nom sur 5 parce
    qu'il cherchait une cellule de tableau qui n'existe plus — le gabarit avait
    change, pas l'accessibilite.

    Le nom arrive parfois prefixe d'un espace insecable de largeur nulle.
    """
    if not page:
        return (None, None)
    m = _RE_1F_NOM.search(page)
    if not m:
        return (None, None)
    nom = m.group(1).replace("​", "").strip()
    if not nom:
        return (None, None)
    t = _RE_1F_TAILLE.search(page)
    if not t:
        return (nom, None)
    try:
        return (nom, int(float(t.group(1).replace(",", ".")) * _FACTEURS_1F[t.group(2).upper()]))
    except (ValueError, KeyError):
        return (nom, None)


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
    if hote == "1fichier.com":
        try:
            code, brut = H._FETCH(url)
        except Exception:                                    # noqa: BLE001
            return False
        if code == 404:
            lien["linkDead"] = True
            return False
        if code != 200:
            # 500 = LIMITATION DE DEBIT, pas un fichier disparu. Les confondre
            # marquerait morts 1330 liens vivants — c'est exactement ce qui a
            # failli arriver le 2026-09-01 sur un balayage trop rapide.
            return False
        nom, taille = _lire_1fichier(brut.decode("utf-8", "replace"))
    elif hote in HOTES:
        nom, taille = H.nom_et_taille(url)
    elif hote in HOTES_TITRE:
        nom, taille = _par_titre(url)
    else:
        return False
    from releves import ressemble_a_un_nom_de_fichier
    if not nom:
        # Rien lu : est-ce que le FICHIER a disparu, ou est-ce nous qui n'avons
        # pas su lire ? La question se tranche, elle ne se suppose pas. Mesure
        # du 2026-08-31 : sur 50 liens sans nom chez ces hotes, 50 rendent 404.
        # Une requete de plus par echec, et le lien cesse d'etre resonde a vie.
        try:
            code, _ = H._FETCH(url)
            if code == 404:
                lien["linkDead"] = True
        except Exception:                                    # noqa: BLE001
            pass
        return False
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
    ap.add_argument("--hotes", default="",
                    help="Ne traiter que ces hotes (fragments, separes par des "
                         "virgules). Sert a donner un rythme PROPRE a un hote "
                         "qui limite — 1fichier rend HTTP 500 des qu'on depasse "
                         "environ une requete par seconde.")
    ap.add_argument("--pause", type=float, default=0.4,
                    help="Secondes d'attente avant chaque lecture (aleatoire, "
                         "entre 0 et cette valeur)")
    ap.add_argument("--releves", type=Path, default=None,
                    help="Ecrire un releve a part au lieu de reecrire le "
                         "catalogue (permet de tourner en parallele d'une autre "
                         "collecte ; voir scripts/releves.py)")
    args = ap.parse_args(argv)

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    filtre = [h.strip() for h in args.hotes.split(",") if h.strip()]
    cibles = [l for pkg in data.get("packages", [])
              for l in (pkg.get("downloadLinks") or [])
              if not l.get("fileName")
              and (H._host(l.get("url", "")) in HOTES + HOTES_TITRE + HOTES_DEDIES
                   or _nom_dans_url(l.get("url", "")))
              and (not filtre or any(h in (l.get("url") or "") for h in filtre))]
    if args.max:
        cibles = cibles[:args.max]
    print(f"{len(cibles)} lien(s) à relever", flush=True)
    if not cibles:
        return 0

    compte = {"poses": 0, "echecs": 0}

    def _un(lien):
        time.sleep(random.random() * args.pause)
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
