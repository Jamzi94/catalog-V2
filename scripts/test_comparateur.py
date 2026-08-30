# -*- coding: utf-8 -*-
"""Le comparateur AVANT de s'en servir : s'il ne voit pas le defaut connu, il est
aveugle et la campagne sur 250 liens ne vaudrait rien."""
import sys, io
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comparateur import comparer, lire_nom, lire_etiquette, mesurable

# TEMOIN POSITIF — le defaut deja etabli : PPSA31246.exfat etiquete PKG.
e = comparer("PPSA31246.exfat", "[PKG] #02")
assert any("format" in x for x in e), e

# TEMOIN NEGATIF — le meme fichier correctement etiquete : rien a signaler.
assert comparer("PPSA31246.exfat", "[exFAT · EUR]") == []

# Un cas reel concordant, releve sur 1fichier le 2026-08-27.
assert comparer("[SuperPSX]-EA.Sports.UFC.5-PPSA03541-EUR-Game (v01.031)-PS5.part01.rar",
                "[v01.031 · PKG · APR-EMU] #01") == []

# Version contredite
e = comparer("[SuperPSX]-Jeu-PPSA00001-EUR-Game (v01.005)-PS5.rar", "[v01.031 · PKG]")
assert any("version" in x for x in e), e

# Region contredite
e = comparer("[SuperPSX]-Jeu-PPSA00001-USA-Game (v01.031)-PS5.rar", "[v01.031 · PKG · EUR]")
assert any("region" in x for x in e), e

# Rang d'affichage : « #n » n'affirme aucun ordre de parties (voir T1 plus bas),
# donc aucun ecart — meme quand le fichier dit part07. Seul « n/N » affirme.
assert comparer("Jeu-PS5.part07.rar", "[PKG] #03") == []
assert comparer("Jeu-PS5.part03.rar", "[PKG] #03") == []

# Mention forte perdue
e = comparer("[SuperPSX]-Jeu-PPSA00001-EUR-DLC-PS5.rar", "[PKG]")
assert any("DLC" in x for x in e), e

# NON MESURABLE — un nom muet ne valide rien. C'est le piege du zero rassurant :
# sans ce garde, tous les noms illisibles compteraient comme « conformes ».
assert comparer("file.rar", "[PKG]") == []
assert not mesurable("file.rar", "[PKG]")
assert mesurable("PPSA31246.exfat", "[PKG] #02")

# Lecture des deux cotes
assert lire_nom("PPSA31246.exfat")["formats"] == ["exFAT"]
assert lire_etiquette("[v01.031 · Backport 4.xx · EUR] #02") == {
    "version": "01.031", "region": "EUR", "formats": ["Backport 4.xx"], "rang": 2}

# Normalisation des versions : le site ecrit « V1.000 » ou « 01.00 » pour la
# meme version que « 01.000 ». Sans ca, l'instrument criait a la contradiction
# 5 fois sur 79 — de la sur-detection, aussi fausse que le zero rassurant.
assert comparer("Jeu V1.000 PPSA00001.rar", "[v01.000 · PKG]") == []
assert comparer("Jeu 01.00 PPSA00001.rar", "[v01.000 · PKG]") == []
# ... mais une VRAIE difference reste vue.
assert comparer("Jeu V1.005 PPSA00001.rar", "[v01.031 · PKG]") != []

# --- T1 : desarmer l'instrument -------------------------------------------
# Regle 1 : « Backport N.xx » IMPLIQUE exFAT. Mesure du 2026-08-30 : sur 732
# liens de cette section dont le nom de fichier a ete releve, 621 disent exFAT
# et AUCUN ne dit PKG. Reprocher l'absence de la mention est de la sur-detection
# — 618 des ecarts. On passe donc la section au comparateur.
assert comparer("PPSA31246.exfat", "[BP 4.xx]", group="Backport 4.xx") == []
assert comparer("PPSA31246.exfat", "[BP]", group="Backport") != []   # sans N.xx : rien n'est implique

# TEMOIN DE DENTS — la regle ne doit pas etre un baillon. Un fichier qui dit PKG
# sous une section Backport N.xx est une VRAIE contradiction et doit sortir.
e = comparer("Jeu-PPSA00001-PKG-PS5.pkg", "[BP 4.xx]", group="Backport 4.xx")
assert e, e

# Regle 2 : la famille « rang » disparait. _number_parts ecrit « #n » comme un
# rang d'affichage et declare explicitement ne pretendre a AUCUN ordre de
# parties : l'instrument accusait l'etiquette d'une affirmation que le code
# refuse de faire.
assert comparer("Jeu-PS5.part07.rar", "[PKG] #03") == []

# ... mais un vrai « n/N », lui, AFFIRME l'ordre : la contradiction reste vue.
e = comparer("Jeu-PS5.part07.rar", "[PKG] 03/10")
assert any("rang" in x for x in e), e

# T1 bis — l'abreviation « BP » de l'etiquette est relue comme « Backport ».
# Sans ca, notre propre abreviation creusait un trou : chaque etiquette BP
# aurait ete comptee « mention Backport absente ».
assert comparer("Jeu-PPSA00001-Backport-PS5.rar", "[BP 4.xx]") == []
assert comparer("Jeu-PPSA00001-Backport-PS5.rar", "[PKG]") != []

print("OK")
