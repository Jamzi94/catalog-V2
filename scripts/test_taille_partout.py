#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La taille s affiche des qu elle est connue ; region et version se corrigent.

DEMANDE du 2026-08-30 : « chaque etiquetage affiche la taille du fichier quand
connu ? ». Elle ne l etait que sur les backports classes correctif — 1057
etiquettes sur 5123 liens dont la taille est connue.

COUT MESURE de la generalisation : la troncature passe de 8,2 % a 10,7 % des
etiquettes au-dela des ~31 caracteres visibles, la longueur moyenne de 17,9 a
19,9. La taille est placee avec le format, donc AVANT la version, qui reste ce
dont on peut le plus se passer — decision de l utilisateur du meme jour.

REGION. Sur les 9 contradictions mesurees, la fiche est muette et c est le
champ region du LIEN, lu sur la rubrique de la page, qui contredit le nom de
fichier. Meme raison que pour le format : le nom decrit le fichier telecharge,
la rubrique decrit le classement de la page.

VERSION. Sur les 110 contradictions, 24 seulement sont decidables : le nom
s accorde avec la FICHE et c est le lien qui diverge — deux sources
independantes contre une. Les 88 autres, ou le nom differe des deux, restent
ouvertes : rien dans le catalogue ne permet de trancher.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import finalize_package                        # noqa: E402

Mo, Go = 1024 ** 2, 1024 ** 3


def _etiq(lien, version_fiche="01.000"):
    pkg = {"titleId": "PPSA00001", "title": "Jeu", "version": version_fiche,
           "downloadLinks": [dict({"url": "https://vikingfile.com/f/a",
                                   "name": "Viki"}, **lien)]}
    finalize_package(pkg, {})
    return pkg["downloadLinks"][0]["name"]


# --- LA TAILLE S AFFICHE DES QU ELLE EST CONNUE -----------------------------
assert "6 Go" in _etiq({"group": "exFAT", "version": "01.000", "sizeBytes": 6 * Go})
assert "45 Mo" in _etiq({"group": "exFAT", "version": "01.000", "sizeBytes": 45 * Mo})
assert "40 Go" in _etiq({"group": "Backport 4.xx", "version": "01.000",
                         "sizeBytes": 40 * Go})

# TEMOIN : sans taille, rien n est invente.
n = _etiq({"group": "exFAT", "version": "01.000"})
assert "Mo" not in n and "Go" not in n, n
# TEMOIN : une taille absurde (zero, negative, texte) n est pas affichee.
for mauvaise in (0, -5, "gros", None):
    n = _etiq({"group": "exFAT", "version": "01.000", "sizeBytes": mauvaise})
    assert "Mo" not in n and "Go" not in n, (mauvaise, n)

# --- REGION : le nom de fichier tranche contre la rubrique ------------------
# Le nom ne l'emporte QUE s'il porte le titleId de CETTE fiche : sur les 9
# contradictions mesurees, 4 portaient celui d'un autre jeu — liens recolles,
# dont la region ne decrit pas ce paquet. Le test_marques_nom le disait deja.
n = _etiq({"group": "Standard", "version": "01.000", "region": "USA",
           "fileName": "Biomutant PPSA00001 v01.003.000 EUR.rar"})
assert "EUR" in n and "USA" not in n, n
# TEMOIN : nom d'un AUTRE jeu -> la region de la rubrique est conservee.
n = _etiq({"group": "Standard", "version": "01.000", "region": "USA",
           "fileName": "Resident Evil 4 PPSA07412 v01.000.000 EUR.rar"})
assert "USA" in n, n
# TEMOIN : un nom muet sur la region ne l efface pas.
n = _etiq({"group": "Standard", "version": "01.000", "region": "USA",
           "fileName": "PPSA06255-un-jeu.rar"})
assert "USA" in n, n

# --- VERSION : le nom confirme la FICHE -> le lien avait tort ---------------
# Le lien dit 01.000, la fiche 01.005.400, le nom de fichier dit 01.005.400.
# La version cesse alors d etre ecrite : elle est celle de la fiche, affichee
# juste au-dessus dans l app.
n = _etiq({"group": "Standard", "version": "01.000",
           "fileName": "[SuperPSX]-Atlas.Fallen-PPSA03388-EUR-Game (v01.005.400)-PS5.rar"},
          version_fiche="01.005.400")
assert "v1.000" not in n, n

# TEMOIN : quand le nom ne confirme PAS la fiche, on ne touche a rien — c est
# le cas des 88 contradictions indecidables.
n = _etiq({"group": "Standard", "version": "01.000",
           "fileName": "jeu-PPSA1 (v02.007)-PS5.rar"}, version_fiche="01.005.400")
assert "v1.000" in n, n

print("OK")
