#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LinkVault : le nom vit dans le <h1>, pas dans <title> ni og:title.

RELEVE sur page reelle le 2026-08-30 (link-vault.org/c/68tx71hg, apres
franchissement du defi Cloudflare) :

    <title>LinkVault | Secure File Aggregation</title>      <- nom du SITE
    og:title                                                <- ABSENT
    <h1 class="...">[SuperPSX]-DOOM.Eternal-PPSA01982-EUR-Game-(v01.011)-PS5</h1>
    <h3 class="text-[14px] font-bold ...">…-PS5.part01.rar</h3>
    <span class="text-[10px] font-black ...">10 GB</span>

Le titre du conteneur porte a lui seul le jeu, le titleId, la region et la
version — tout ce dont l etiquetage a besoin. Le <title>, lui, est le nom du
site, et le garde ressemble_a_un_nom_de_fichier le rejette a juste titre.

CE QUE CETTE PAGE NE DONNE PAS : les URL reelles des miroirs. Mesure : sur les
83 Ko du HTML rendu, ZERO occurrence de « gofile.io/d/ », « vikingfile.com/f/ »,
« 1fichier.com/? » ou « rootz.so/d/ ». Elles ne vivent que dans l etat React et
ne transitent que par une API protegee par Turnstile. On ne peut donc PAS
remplacer un lien link-vault par ses miroirs a partir du seul rendu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lire_akirabox import extraire_nom_taille                        # noqa: E402

Go = 1024 ** 3

PAGE = ('<title>LinkVault | Secure File Aggregation</title>'
        '<div class="text-center mb-10"><h1 class="text-2xl md:text-3xl font-black '
        'text-white tracking-tighter uppercase italic drop-shadow-2xl">'
        '[SuperPSX]-DOOM.Eternal-PPSA01982-EUR-Game-(v01.011)-PS5</h1></div>'
        '<h3 class="text-[14px] font-bold tracking-tight leading-snug break-all '
        'sm:break-words text-white/90">'
        '[SuperPSX]-DOOM.Eternal-PPSA01982-EUR-Game-(v01.011)-PS5.part01.rar</h3>'
        '<span class="text-[10px] font-black text-white/20 uppercase tracking-widest">'
        '10 GB</span>'
        '<span class="...">Available</span>')

nom, taille = extraire_nom_taille(PAGE)
assert nom == "[SuperPSX]-DOOM.Eternal-PPSA01982-EUR-Game-(v01.011)-PS5", nom
assert taille == 10 * Go, taille

# TEMOIN : un <h1> qui n est PAS un nom de fichier ne passe pas le garde.
sans = PAGE.replace("[SuperPSX]-DOOM.Eternal-PPSA01982-EUR-Game-(v01.011)-PS5</h1>",
                    "Bienvenue sur LinkVault</h1>", 1)
n2, _ = extraire_nom_taille(sans)
assert n2 != "Bienvenue sur LinkVault", n2

# TEMOIN : le <title> du site ne doit JAMAIS servir de nom, meme sans h1.
titre_seul = '<title>LinkVault | Secure File Aggregation</title><p>rien</p>'
assert extraire_nom_taille(titre_seul) == (None, None)

print("OK")
