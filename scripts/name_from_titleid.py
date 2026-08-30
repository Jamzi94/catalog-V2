#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renomme depuis Sony les fiches dont le titre ne nomme aucun jeu.

Pourquoi. Les pages de telechargement de superpsx.com ne portent PAS le nom du
jeu : le fil d'ariane et og:title donnent le slug de page (« DLL-SH2PS5 ») et le
seul <h1> du document est celui d'un widget de dons en barre laterale
(« CyB1K Need Us! », releve le 2026-08-27). Le scraper prenait l'un ou l'autre :
15 fiches du catalogue portaient « CyB1K Need Us! » pour 15 jeux DIFFERENTS, une
autre s'appelait « DLL-NBA2K25PS5 ».

scrape_superpsx.py ne produit plus ces titres — il rend desormais un titre vide
plutot qu'un libelle emprunte. Reste a NOMMER ces fiches : sur ces pages, la
seule identite fiable est le titleId (« Version ⇛ PPSA08709 – EUR »), que le
scraper releve deja. PROSPEROPatches rend le nom officiel Sony par titleId.

Ce script ne touche QUE les fiches dont le titre est juge sans valeur, et jamais
celles qui ont un titre plausible : il repare, il n'harmonise pas.

Usage :
  python scripts/name_from_titleid.py ps5-catalog.json            # sur place
  python scripts/name_from_titleid.py ps5-catalog.json --dry-run  # rien n'est ecrit
  python scripts/name_from_titleid.py --selftest                  # sans reseau
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://prosperopatches.com/{}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
REAL_TITLEID_RE = re.compile(r"^[A-Z]{4}\d{3,}$")
# Au-dela de 2 titleId REELS pour un meme libelle, ce n'est plus un jeu edite en
# plusieurs regions, c'est un libelle emprunte. Distribution mesuree sur le
# catalogue du 2026-08-27 : 878 titres portes par 1 fiche, 57 par 2, puis
# directement 1 titre porte par 15. Aucune zone grise autour du seuil.
SEUIL_LIBELLE_EMPRUNTE = 3
# CE SEUIL NE DECIDE PAS, IL PROPOSE. Mesure du 2026-08-30, une fois les CyB1K
# renommes : la distribution est devenue {1 titleId : 862 titres, 2 : 75,
# 3 : 1} — et l'unique titre porte par 3 titleId REELS est « Tactics Ogre:
# Reborn », un vrai jeu en trois SKU regionaux. Le seuil ne produit donc plus
# aujourd'hui qu'un faux positif sur un.
#
# J'ai cherche un meilleur discriminant et je l'ai REFUTE : l'idee que des
# editions regionales portent des titleId proches ne tient pas. Ecarts mesures
# entre porteurs d'un meme titre, tous de vrais jeux : 1, 2, 22, 360, 901,
# 4799, 5901, 15263, et 16384 pour « Horizon Forbidden West Complete Edition ».
# La proximite numerique ne dit rien.
#
# Le seul discriminant fiable est Sony, et il est DEJA interroge : si le nom
# officiel egale le titre courant, le libelle n'etait pas emprunte — c'est un
# jeu multi-SKU, on ne touche a rien. Voir la boucle de main().
# Libelles deja pris la main dans le sac. Le seuil ci-dessus s'evalue sur l'etat
# COURANT du catalogue : une fois ses jumelles renommees, la derniere fiche
# portant le meme libelle n'est plus portee que par 1 titleId et passe sous le
# seuil — vu le 2026-08-27, PPSA13222 est reste « CyB1K Need Us! » parce que la
# source avait rendu une erreur a son tour de boucle. Cette liste rattrape le
# trainard et la reapparition du meme encart.
LIBELLES_EMPRUNTES_CONNUS = {"cyb1k need us!"}


def _slug(titre: str) -> bool:
    """Une reference de page, pas un nom de jeu (meme regle que scrape_superpsx)."""
    t = (titre or "").strip()
    if re.fullmatch(r"\d+[-–]\d+", t):
        return True
    if re.match(r"(?i)^dll[-_]", t):
        return True
    return bool(re.fullmatch(r"(?i)[A-Z0-9._-]{6,}PS5", t))


def titres_sans_valeur(packages: list) -> dict:
    """{titleId: motif} des fiches a renommer. Ne juge que le titre."""
    portes = collections.defaultdict(set)
    for p in packages:
        tid = (p.get("titleId") or "").strip().upper()
        if REAL_TITLEID_RE.match(tid):
            portes[(p.get("title") or "").strip()].add(tid)
    a_faire = {}
    for p in packages:
        titre = (p.get("title") or "").strip()
        tid = (p.get("titleId") or "").strip().upper()
        if not titre:
            motif = "titre vide"
        elif _slug(titre):
            motif = "slug de page"
        elif titre.lower() in LIBELLES_EMPRUNTES_CONNUS:
            motif = "libelle emprunte connu"
        elif len(portes.get(titre, ())) >= SEUIL_LIBELLE_EMPRUNTE:
            motif = f"libelle porte par {len(portes[titre])} titleId reels"
        else:
            continue
        a_faire[tid or f"(sans titleId) {titre}"] = motif
    return a_faire


def nettoyer(nom: str) -> str:
    """Retire les symboles de marque, rien d'autre : on ne reecrit pas Sony."""
    nom = re.sub(r"[™®©]", "", nom or "")
    return re.sub(r"\s+", " ", nom).strip()


def nom_officiel(title_id: str, cache: dict) -> str | None:
    if title_id in cache:
        return cache[title_id]
    try:
        req = urllib.request.Request(SOURCE.format(title_id), headers=UA)
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as exc:                                    # noqa: BLE001
        print(f"  {title_id} : injoignable ({exc})")
        cache[title_id] = None
        return None
    m = re.search(r"<title>([^<]*)</title>", html)
    brut = (m.group(1) if m else "").strip()
    nom = brut.split(":", 1)[1].strip() if ":" in brut else ""
    if not nom or nom.lower().startswith("page not found"):
        nom = ""
    cache[title_id] = nettoyer(nom) or None
    return cache[title_id]


def _selftest() -> int:
    """Detection hors reseau, avec ses temoins negatifs."""
    assert _slug("DLL-SH2PS5") and _slug("26528-2626") and _slug("DLL-NBA2K25PS5")
    assert not _slug("Silent Hill 2") and not _slug("MLB The Show 21")
    assert nettoyer("EA SPORTS™ UFC® 5") == "EA SPORTS UFC 5"
    pk = ([{"titleId": f"PPSA0000{i}", "title": "CyB1K Need Us!"} for i in range(3)]
          + [{"titleId": "PPSA11111", "title": "DLL-SH2PS5"},
             {"titleId": "PPSA22222", "title": ""},
             {"titleId": "PPSA33333", "title": "Silent Hill 2"},
             # temoin negatif : deux editions regionales d'un meme jeu se
             # partagent legitimement un titre, elles ne doivent PAS bouger
             {"titleId": "PPSA44444", "title": "Bugsnax"},
             {"titleId": "PPSA55555", "title": "Bugsnax"}])
    a = titres_sans_valeur(pk)
    assert len(a) == 5, a
    assert "PPSA33333" not in a and "PPSA44444" not in a and "PPSA55555" not in a, a
    assert a["PPSA11111"] == "slug de page" and a["PPSA22222"] == "titre vide"
    # Trainard : seul porteur du libelle emprunte, sous le seuil, rattrape par la
    # liste. Temoin negatif juste apres : un titre normal ne bouge pas.
    seul = titres_sans_valeur([{"titleId": "PPSA66666", "title": "CyB1K Need Us!"},
                               {"titleId": "PPSA77777", "title": "Tiger Blade"}])
    assert seul == {"PPSA66666": "libelle emprunte connu"}, seul
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path, nargs="?")
    ap.add_argument("--out", type=Path, default=None, help="Sortie (defaut : sur place)")
    ap.add_argument("--dry-run", action="store_true", help="Montre sans ecrire")
    ap.add_argument("--selftest", action="store_true", help="Controle hors reseau")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.catalog:
        ap.error("indiquer un catalogue, ou --selftest")

    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    packages = data.get("packages", [])
    a_faire = titres_sans_valeur(packages)
    print(f"{len(a_faire)} fiche(s) au titre sans valeur sur {len(packages)}")
    if not a_faire:
        return 0

    cache: dict = {}
    renommees = echecs = confirmees = 0
    for pkg in packages:
        tid = (pkg.get("titleId") or "").strip().upper()
        if tid not in a_faire:
            continue
        nom = nom_officiel(tid, cache) if REAL_TITLEID_RE.match(tid) else None
        if not nom:
            echecs += 1
            print(f"  {tid or '(vide)'} : NON RENOMMEE ({a_faire[tid]}) — "
                  f"titre laisse tel quel : {pkg.get('title')!r}")
            continue
        if nom == (pkg.get("title") or "").strip():
            # Sony confirme le titre courant : le seuil avait propose a tort.
            # Un jeu en plusieurs SKU regionaux partage legitimement son nom.
            print(f"  {tid} : {nom!r} confirme par Sony — inchange "
                  f"[proposee par : {a_faire[tid]}]")
            confirmees += 1
            continue
        print(f"  {tid} : {pkg.get('title')!r} -> {nom!r}   [{a_faire[tid]}]")
        if not args.dry_run:
            pkg["title"] = nom
        renommees += 1
    # Les fiches sans titleId reel ne sont pas dans la boucle ci-dessus.
    echecs += sum(1 for k in a_faire if not REAL_TITLEID_RE.match(k))
    if echecs and not args.dry_run:
        # Un echec isole vient plus souvent d'un hoquet de la source que d'un
        # titleId inconnu : on retente une fois, cache des echecs vide.
        restants = {t for t, v in cache.items() if v is None}
        for t in restants:
            del cache[t]
        for pkg in packages:
            tid = (pkg.get("titleId") or "").strip().upper()
            if tid not in restants or tid not in a_faire:
                continue
            nom = nom_officiel(tid, cache)
            if nom:
                print(f"  {tid} (2e essai) : {pkg.get('title')!r} -> {nom!r}")
                pkg["title"] = nom
                renommees += 1
                echecs -= 1
    print(f"\n{renommees} renommee(s), {confirmees} confirmee(s) par Sony donc inchangee(s), "
          f"{echecs} laissee(s) en l'etat (pas de titleId exploitable ou source muette)")
    if args.dry_run:
        print("--dry-run : rien n'a ete ecrit")
        return 0
    out = args.out or args.catalog
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ecrit : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
