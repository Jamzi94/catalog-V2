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

DEUX VOIES, et la seconde a ete decouverte en capturant la page :

  --navigateur : un Chrome pilote localement. Le defi Cloudflare ne se joue
      QU'UNE FOIS PAR SESSION — mesure du 2026-08-30 : la premiere page met
      ~18 s, la suivante s'ouvre instantanement dans le meme contexte. Un
      balayage des 2904 liens redevient donc possible sans rien installer. Mon
      premier essai avait conclu « bloque » parce qu'il n'attendait que 6 s :
      l'instrument etait trop presse, pas le site infranchissable.
  FlareSolverr : la voie de la CI, ou cinq instances tournent deja.

Ce module s'execute donc en CI, ou en local si l'on renseigne
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
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_FACTEURS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4,
             "KO": 1024, "MO": 1024 ** 2, "GO": 1024 ** 3, "TO": 1024 ** 4}


def _octets(nombre: str, unite: str):
    try:
        return int(float(nombre.replace(",", ".")) * _FACTEURS[unite.upper().replace("I", "")])
    except (ValueError, KeyError):
        return None


def _extraire_brut(page: str) -> tuple:
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

    # 0) og:description — l'ancre d'akirabox, relevee sur une page REELLE le
    #    2026-08-30 apres franchissement du defi :
    #      « Download <nom> (9.9 GB) now. Fast and easy at akirabox.com »
    #    Elle porte le nom ET la taille, et elle est la seule du document a le
    #    faire : le titre, lui, colle un suffixe « - Akira Box » au nom.
    marque = "og:description" + chr(34) + " content=" + chr(34)
    i = page.find(marque)
    if i >= 0:
        j = page.find(chr(34), i + len(marque))
        desc = page[i + len(marque):j] if j > 0 else ""
        m = re.match(r"^Download[ ]+(.*?)[ ]*\(([0-9.,]+)[ ]*([KMGT]?i?B|[KMGT]?o)\)", desc)
        if m:
            return (m.group(1).strip(), _octets(m.group(2), m.group(3)))

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
            return (titre, _taille_span_size(page) or _taille_pres_de(page, m.start()))
    return (None, None)


def extraire_nom_taille(page: str) -> tuple:
    """(nom, octets), ou (None, None) si le nom releve n'en est pas un.

    Le 2026-08-30, la sonde gofile a rendu 64 noms sur 120 et j'allais compter
    ça comme un succes : 61 d'entre eux etaient « Content not found · Gofile »,
    pris dans og:title, dont le cas acceptait n'importe quel texte. Un parseur
    qui n'a jamais vu un gabarit ne rend pas « erreur » — il rend un resultat
    plausible. Le garde vit dans releves.py, partage avec relever_noms.
    """
    from releves import ressemble_a_un_nom_de_fichier
    nom, octets = _extraire_brut(page)
    if not ressemble_a_un_nom_de_fichier(nom):
        return (None, None)
    return (nom, octets)


def _taille_span_size(page: str):
    """Taille annoncee par <span class="size">52.5GB</span> — gabarit buzzheavier.

    Releve sur page reelle le 2026-08-30 (buzzheavier.com/a2bz5qkvml2w) :

        <a class="download-btn gay-button" hx-get="/…/download?t=…">
            Download File <span class="size">52.5GB</span></a>

    Pourquoi une ancre plutot que la fenetre de _taille_pres_de : le titre est
    dans les 300 premiers octets, ce span vers la fin d'une page de 5900, et la
    fenetre de 4000 caracteres le manquait une fois sur deux — 3 tailles pour 13
    noms au run 33291251093. Une ancre ne depend pas de la mise en page.
    """
    m = re.search('class="[^"]*size[^"]*"[^>]*>([0-9][0-9.,]*) *'
                  r'([KMGT]i?B|[KMGT]o)', page)
    return _octets(m.group(1), m.group(2)) if m else None


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
    # parse_flaresolverr_urls rend une valeur par defaut meme sans variable
    # d'environnement, et le constructeur leve si aucune instance ne repond.
    # Hors CI c'est le cas NORMAL, pas une panne : on rend None et le script
    # dit ce qu'il aurait fait au lieu de cracher une pile.
    try:
        return FlareSolverrPool(urls)
    except Exception as exc:                                 # noqa: BLE001
        print(f"FlareSolverr injoignable ({exc.__class__.__name__})")
        return None


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--hotes", default="akirabox",
                    help="Fragments d hote a traiter, separes par des virgules. "
                         "buzzheavier est passe derriere le meme defi Cloudflare "
                         "le 2026-08-30 ; son gabarit de page n est PAS encore "
                         "confronte au parseur : resultat a mesurer.")
    ap.add_argument("--releves", type=Path, default=None,
                    help="Ecrire un releve a part au lieu de reecrire le "
                         "catalogue (permet de tourner en parallele d'une autre "
                         "collecte ; voir scripts/releves.py)")
    ap.add_argument("--fils", type=int, default=0,
                    help="Pages menees de front (0 = une par instance "
                         "FlareSolverr, ce qui est le bon reglage : chaque "
                         "instance a sa propre session Chrome).")
    ap.add_argument("--pause", type=float, default=0.8,
                    help="Secondes entre deux pages (politesse)")
    ap.add_argument("--navigateur", action="store_true",
                    help="Piloter un Chrome local au lieu de FlareSolverr")
    args = ap.parse_args(argv)

    pool = None if args.navigateur else _pool()
    if pool is None and not args.navigateur:
        print("FLARESOLVERR_URLS non renseigné — rien à faire ici. "
              "Ce script s'exécute en CI, où cinq instances tournent.")
        return 0

    hotes = [h.strip() for h in args.hotes.split(",") if h.strip()]
    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    cibles = [l for pkg in data.get("packages", [])
              for l in (pkg.get("downloadLinks") or [])
              if any(h in l.get("url", "") for h in hotes)
              and not l.get("fileName")]
    if args.max:
        cibles = cibles[:args.max]
    print(f"{len(cibles)} page(s) a lire chez {hotes}", flush=True)

    navigateur = page = contexte = None
    if args.navigateur:
        from playwright.sync_api import sync_playwright
        contexte = sync_playwright().start()
        navigateur = contexte.chromium.launch(headless=True)
        page = navigateur.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="fr-FR")

    noms = tailles = echecs = 0
    verrou = threading.Lock()

    def _une(paire):
        """Lit UNE page. Rend (lien, nom, octets) ; ne touche a rien de partage."""
        i, lien = paire
        try:
            if args.navigateur:
                page.goto(lien["url"], timeout=60000, wait_until="domcontentloaded")
                # Le defi ne se joue qu'a la premiere page : on lui laisse le
                # temps une fois, puis les suivantes arrivent tout de suite.
                for _ in range(24):
                    if "akira box" in (page.title() or "").lower():
                        break
                    page.wait_for_timeout(1000)
                contenu = page.content()
            else:
                contenu = getattr(pool.get(lien["url"]), "text", "") or ""
            nom, octets = extraire_nom_taille(contenu)
        except Exception:                                    # noqa: BLE001
            nom, octets = None, None
        # POLITESSE, apprise a mes depens le 2026-08-30 : 850 pages tirees en
        # deux salves a douze fils ont fait durcir le defi Cloudflare pour toute
        # la session — il ne se resolvait plus, meme apres 45 s d'attente. Un
        # balayage force n'accelere rien, il ferme la porte. Ici la pause est
        # PAR FIL, et il y a un fil par instance FlareSolverr : chaque session
        # Chrome garde donc son propre rythme, celui qui a marche.
        if args.pause:
            time.sleep(args.pause + random.random() * args.pause)
        return (lien, nom, octets, i)

    def _ranger(res):
        nonlocal noms, tailles, echecs
        lien, nom, octets, i = res
        with verrou:
            if nom:
                lien["fileName"] = nom
                noms += 1
                if octets:
                    lien["sizeBytes"] = octets
                    tailles += 1
            else:
                echecs += 1
            fait = noms + echecs
            if fait % 50 == 0:
                print(f"  {fait}/{len(cibles)} — {noms} noms, {echecs} echecs", flush=True)

    # UN FIL PAR INSTANCE FlareSolverr. Le pool est deja concurrent — il protege
    # son round-robin par un verrou et scrape_superpsx.py s'en sert ainsi depuis
    # toujours. lire_akirabox, lui, lisait UNE page a la fois : sur le run
    # 33288861281, cette etape a depasse douze minutes avec cinq instances
    # inoccupees a quatre cinquiemes.
    # pool.size est une PROPRIETE (@property dans flaresolverr_pool), pas une
    # methode. Ecrit pool.size(), il levait « 'int' object is not callable » et
    # les deux collectes mouraient en une seconde — run 33290443896.
    fils = args.fils or (1 if args.navigateur else max(1, pool.size))
    if fils <= 1:
        for paire in enumerate(cibles, 1):
            _ranger(_une(paire))
    else:
        print(f"  {fils} page(s) de front", flush=True)
        with ThreadPoolExecutor(max_workers=fils) as ex:
            for res in ex.map(_une, enumerate(cibles, 1)):
                _ranger(res)

    if navigateur is not None:
        navigateur.close()
        contexte.stop()
    if args.releves:
        import releves
        n = releves.ecrire(args.releves, cibles)
        print(f"{n} releve(s) ecrit(s) dans {args.releves}"
              " — le catalogue n est PAS touche ici")
    else:
        args.catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    print(f"{noms} nom(s), {tailles} taille(s), {echecs} échec(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
