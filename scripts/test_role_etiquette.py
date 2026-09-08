#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chaque etiquette commence par le ROLE : GAME, UPD, DLC, FIX.

POURQUOI. Des clients disent ne plus s y retrouver, et la mesure leur donne
raison. Sur le catalogue publie : 820 grammaires d etiquettes differentes,
22,2 caracteres de moyenne pour ~31 visibles, 16 % tronquees, et une mediane de
12 liens par fiche (jusqu a 99 sur « The Elder Scrolls IV Oblivion »).

Ce que voyait un client sur « Split Fiction », 97 liens :

    [PKG · Folder · FFPFSC · FFPKG · BP · 81 M▒   vikingfile
    [PKG · Folder · FFPFSC · FFPKG · USA · v1.▒   1fichier
    [exFAT · BP 4.xx · 66 Go]                     datanodes
    [BP · fix · USA · v1.500] #01                 rootz

Le jargon occupe la tete, le discriminant passe sous l ellipse, et la question
qu on se pose d abord — « lequel je telecharge pour JOUER ? » — n a de reponse
nulle part. Le role la donne, et il se lit en premier.

CE SUR QUOI IL SE BASE, entierement deja mesure :
  FIX  classer_par_nom tranche jeu/correctif a 99 % d exactitude sur 1206
       liens de controle ; la taille ne departage que ce qu il laisse inconnu.
  DLC  releve dans le nom de fichier, 1769 etiquettes le portent aujourd hui.
  UPD  version du lien differente de celle de la fiche.
  GAME tout le reste.

LE JARGON SORT DE L AFFICHAGE, pas de la donnee. Mesure : FFPKG n apparait
JAMAIS sans PKG (145 sur 145), FFPFSC 391 fois sur 422, Folder 2472 sur 2721.
Folder seul coute 9 caracteres sur 15 % des etiquettes pour dire ce que
l utilisateur verra en telechargeant.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import finalize_package, role_du_lien           # noqa: E402

Mo, Go = 1024 ** 2, 1024 ** 3


# --- le role, isolement -----------------------------------------------------
assert role_du_lien({"fileName": "Jeu-PPSA1-DLC-EUR.rar"}, "01.000") == "DLC"
assert role_du_lien({"group": "exFAT · DLC"}, "01.000") == "DLC"
assert role_du_lien({"fileName": "jeu-fix.rar", "sizeBytes": 40 * Mo}, "01.000") == "FIX"
assert role_du_lien({"sizeBytes": 40 * Mo}, "01.000") == "FIX", "petit = binaire a deposer"
assert role_du_lien({"sizeBytes": 40 * Go}, "01.000") == "GAME"
assert role_du_lien({"version": "01.005"}, "01.000") == "UPD", "version differente de la fiche"
assert role_du_lien({"version": "01.000"}, "01.000") == "GAME"
assert role_du_lien({}, "01.000") == "GAME", "sans indice, c est le jeu"

# PRIORITES. Un DLC reste un DLC meme petit : ce qu on cherche, c est le
# contenu, pas sa taille. Et un correctif de version differente reste un FIX.
assert role_du_lien({"fileName": "All_DLCs.rar", "sizeBytes": 4 * Mo}, "01.000") == "DLC"
assert role_du_lien({"fileName": "jeu-fix.rar", "version": "01.005"}, "01.000") == "FIX"


def _etiq(liens, version="01.000"):
    pkg = {"titleId": "PPSA00001", "title": "Jeu", "version": version,
           "downloadLinks": [dict({"url": f"https://v/{i}", "name": "V"}, **l)
                             for i, l in enumerate(liens)]}
    finalize_package(pkg, {})
    return [l.get("name") for l in pkg["downloadLinks"]]


# --- le role est EN TETE ----------------------------------------------------
n = _etiq([{"group": "exFAT", "sizeBytes": 66 * Go, "fileName": "PPSA1.exfat"}])
# Separateur : espace simple depuis le 2026-09-08 — « · » entoure
# d espaces coutait 21 points de troncature a lui seul.
assert n[0].startswith("[GAME "), n

# --- le jargon sort de l AFFICHAGE ------------------------------------------
# DECISION du 2026-09-08 : le format s affiche EN ENTIER. Ce temoin verifiait
# l inverse — que « Folder », « FFPFSC » et « FFPKG » etaient masques. La
# mesure qui le motivait tenait (FFPKG n apparait jamais sans PKG, 145 sur
# 145), la conclusion non : ces mots disent ce qu on va MANIPULER une fois le
# fichier telecharge, et un dossier ne s installe pas comme une archive.
n = _etiq([{"group": "PKG · Folder · FFPFSC", "fileFormat": "FFPKG",
            "sizeBytes": 66 * Go, "fileName": "jeu.pkg"}])
for mot in ("PKG", "Folder", "FFPFSC"):
    assert mot in n[0], (mot, n)
# TEMOIN : ce qui DECIDE de la compatibilite reste — exFAT et BP N.xx.
n = _etiq([{"group": "exFAT · Backport 4.xx", "sizeBytes": 66 * Go,
            "fileName": "PPSA1.exfat"}])
assert "exFAT" in n[0] and "BP 4.xx" in n[0], n

# --- LA LISTE EST TRIEE : GAME, UPD, DLC, FIX -------------------------------
n = _etiq([
    {"fileName": "jeu-fix.rar", "sizeBytes": 40 * Mo},
    {"fileName": "All_DLCs.rar", "sizeBytes": 2 * Go},
    {"sizeBytes": 66 * Go, "fileName": "PPSA1.exfat"},
    {"version": "01.005", "sizeBytes": 3 * Go},
])
roles = [x.lstrip("[").split(" ")[0] for x in n]
assert roles == ["GAME", "UPD", "DLC", "FIX"], roles

# TEMOIN : a role egal, l ordre d origine est CONSERVE — sinon les parties
# d une archive decoupee et les miroirs d un meme fichier se disperseraient.
n = _etiq([{"sizeBytes": 10 * Go, "fileName": f"jeu.part0{i}.rar"} for i in (1, 2, 3)])
# Le numero precede desormais le role : « lequel est-ce » passe avant « a
# quoi ça sert » quand on assemble douze fichiers.
assert all(" GAME " in r for r in n), n
assert [x[1:6] for x in n] == ["01/03", "02/03", "03/03"], n


# --- UPD n est pas « version differente » -----------------------------------
# Mesure du 2026-09-08 : sur 850 liens classes UPD dont la taille est connue,
# 704 depassent 5 Go et 286 depassent 20 Go — dont un « PPSA26786.exfat » de
# 230 Go. Une mise a jour PS5 ne pese pas 230 Go : c est le JEU, dans une autre
# version, et il se retrouvait relegue derriere les GAME alors que c est lui
# qu on vient chercher.
#
# Le nom prime, comme partout ailleurs ici : si classer_par_nom dit « jeu »
# (image exFAT, archive en parties), c est un GAME quelle que soit sa version.
assert role_du_lien({"fileName": "PPSA26786.exfat", "version": "02.000"}, "01.000") == "GAME"
assert role_du_lien({"fileName": "jeu.part01.rar", "version": "02.000"}, "01.000") == "GAME"
# ... et une vraie mise a jour, que le nom ne dit pas « jeu », reste UPD.
assert role_du_lien({"fileName": "patch-1.05.pkg", "version": "01.005"}, "01.000") == "UPD"
assert role_du_lien({"version": "01.005"}, "01.000") == "UPD"
# TEMOIN : la taille seule ne suffit pas a faire un GAME — un gros fichier dont
# le nom se tait et dont la version differe reste une mise a jour possible.
# On ne bascule que sur ce que le NOM affirme.
assert role_du_lien({"sizeBytes": 40 * Go, "version": "01.005"}, "01.000") == "UPD"

print("OK")
