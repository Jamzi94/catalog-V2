#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un titre de site n est pas un nom de fichier.

INCIDENT du 2026-08-30. La sonde gofile a rendu 64 noms sur 120 et j allais
compter ça comme un succes. Elle avait ecrit « Content not found · Gofile »
dans fileName sur 61 liens : le parseur prend og:title, et le cas og:title
acceptait N IMPORTE QUEL texte. Un parseur qui n a jamais vu un gabarit ne rend
pas « erreur » — il rend un resultat plausible, et ce nom-la serait ensuite
passe dans marques_du_nom et region_du_nom pour ETIQUETER les liens.

PREMIERE tentative de garde, ecartee : une liste de mots d erreur (« not
found », « 404 », « error »…). Elle rejetait « PPSA14404.exfat » parce que le
titleId contient 404, et « Quantum.Error…rar » parce que c est le nom du jeu.
La sur-detection est le meme defaut a l envers.

Le critere retenu ne cherche pas l erreur, il cherche le FICHIER : une
extension, ou un identifiant Sony. Mesure sur les 10630 noms deja releves :
71 rejets, soit 0,67 %, dont 70 sont de vrais titres de site.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from releves import ressemble_a_un_nom_de_fichier as ok                # noqa: E402

# --- ce qui doit PASSER : tous releves sur des pages reelles ----------------
assert ok("PPSA05366.exfat")
assert ok("[SuperPSX]-Bendy.and.The.Ink.Machine-PPSA01234-EUR-Game-PS5.rar")
assert ok("PPSA14396 exfat"), "datavaults remplace le point par une espace"
assert ok("All DLCs Pkykzhack rar")
assert ok("PPSA01285.ffpkg")
assert ok("[ Remnant 2 ]-[DLPSGAME.COM].rar")
assert ok("duplex-PPSA04405.ps5-[DLPSGAME.COM].rar")
assert ok("jeu.part01.rar")
# TEMOINS des faux positifs de la premiere tentative : le titleId contient 404,
# le nom du jeu contient « Error ». Les deux DOIVENT passer.
assert ok("PPSA14404.exfat")
assert ok("[SuperPSX]-Quantum.Error-PPSA04479-USA-Game-v01.00-PS5.rar")
# Un nom sans extension mais avec identifiant Sony reste un nom de fichier.
assert ok("4_XX PPSA04048_-_USA_V1_17_LEGO_2K_Drive_Backport__By_BADERLINK-")

# --- ce qui doit ETRE REJETE : titres de site releves dans le catalogue -----
assert not ok("Content not found · Gofile")
assert not ok("Files · Gofile")
assert not ok("Gofile — Cloud Storage Made Simple")
assert not ok("Akira Box - Folder - DLCs")
assert not ok("Data Vaults | Free Unlimited Files Upload Services")
assert not ok("Not Found")
assert not ok("")
assert not ok(None)

print("OK")
