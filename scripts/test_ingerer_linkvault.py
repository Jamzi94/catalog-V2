#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Un conteneur LinkVault se remplace par les liens qu il agrege.

Un lien link-vault.org/c/<slug> n heberge RIEN : c est une page qui agrege les
miroirs. Pour « DOOM Eternal », un seul conteneur porte 32 liens reels — 8
parties x Gofile, Vikingfile, 1Fichier, Rootz — chacun avec son nom de fichier
complet, sa taille, et son etat de disponibilite audite la veille.

MESURE du 2026-08-30 : les 8 liens Gofile de ce conteneur sont ABSENTS du
catalogue. Le conteneur apporte donc du contenu neuf, il ne double pas
l existant. Sur 40 conteneurs releves : 453 liens, 0 desaccord nom/URL.

Le lien link-vault est RETIRE une fois resolu : il ne menait a aucun fichier.
Les nouveaux liens heritent de sa section et de sa version — ce que la page
source disait du paquet reste vrai des fichiers qu il contient.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingerer_linkvault import ingerer, taille_en_octets                # noqa: E402

Go, Mo = 1024 ** 3, 1024 ** 2

# --- lecture des tailles telles que LinkVault les ecrit ---------------------
assert taille_en_octets("10 GB") == 10 * Go
assert taille_en_octets("8.58 GB") == int(8.58 * Go)
assert taille_en_octets("169.09 MB") == int(169.09 * Mo)
assert taille_en_octets("10.00 GB") == 10 * Go
assert taille_en_octets("") is None and taille_en_octets(None) is None
assert taille_en_octets("beaucoup") is None


def _cat():
    return {"packages": [{"titleId": "PPSA01982", "title": "DOOM Eternal",
        "downloadLinks": [
            {"url": "https://link-vault.org/c/68tx71hg", "group": "exFAT · Backport 4.xx",
             "version": "01.011", "name": "Multihost"},
            {"url": "https://vikingfile.com/f/DEJA", "fileName": "deja-la.rar"},
        ]}]}


RELEVE = {"68tx71hg": {"titre": "[SuperPSX]-DOOM.Eternal-PPSA01982-EUR-Game-(v01.011)-PS5",
    "hotes": {
        "Gofile": [{"url": "https://gofile.io/d/2D3eu3uM",
                    "nom": "…-PS5.part01.rar", "taille": "10 GB"}],
        "1Fichier": [{"url": "https://1fichier.com/?abc&af=1",
                      "nom": "…-PS5.part01.rar", "taille": "10.00 GB"}],
        # un hote en desaccord n est PAS ingere : on n apparie pas au hasard
        "Rootz": {"desaccord": [3, 8]},
    }}}

cat = _cat()
stats = ingerer(cat, RELEVE)
liens = cat["packages"][0]["downloadLinks"]
urls = [l["url"] for l in liens]

# le conteneur a disparu, les vrais liens l ont remplace
assert "https://link-vault.org/c/68tx71hg" not in urls, urls
assert "https://gofile.io/d/2D3eu3uM" in urls
assert "https://1fichier.com/?abc&af=1" in urls
# TEMOIN : l hote en desaccord n a rien apporte
assert not any("rootz" in u for u in urls), urls
# TEMOIN : ce qui existait deja n a pas bouge
assert "https://vikingfile.com/f/DEJA" in urls

neuf = next(l for l in liens if "gofile" in l["url"])
assert neuf["fileName"] == "…-PS5.part01.rar"
assert neuf["sizeBytes"] == 10 * Go
assert neuf["group"] == "exFAT · Backport 4.xx", "la section du conteneur est heritee"
assert neuf["version"] == "01.011"
assert stats["ajoutes"] == 2 and stats["conteneurs_resolus"] == 1, stats

# --- un conteneur SANS releve reste intact ---------------------------------
cat2 = _cat()
s2 = ingerer(cat2, {})
assert any("link-vault" in l["url"] for l in cat2["packages"][0]["downloadLinks"])
assert s2["ajoutes"] == 0

# --- un lien deja present n est pas duplique -------------------------------
cat3 = _cat()
cat3["packages"][0]["downloadLinks"].append({"url": "https://gofile.io/d/2D3eu3uM"})
ingerer(cat3, RELEVE)
u3 = [l["url"] for l in cat3["packages"][0]["downloadLinks"]]
assert u3.count("https://gofile.io/d/2D3eu3uM") == 1, u3


# --- l ETAT que LinkVault donne gratuitement --------------------------------
# Chaque ligne porte « Available » et la date du dernier audit. C est la seule
# source du catalogue qui sache dire si un lien 1fichier est vivant : cet hote
# ne se sonde pas autrement. Un lien annonce mort entre marque, pas ignore —
# il reste dans la donnee et disparait a l affichage, comme les 404.
RELEVE_ETAT = {"68tx71hg": {"titre": "T", "hotes": {"Gofile": [
    {"url": "https://gofile.io/d/VIVANT", "nom": "a.rar", "taille": "1 GB",
     "etat": "Available"},
    {"url": "https://gofile.io/d/MORT", "nom": "b.rar", "taille": "1 GB",
     "etat": "Unavailable"},
    {"url": "https://gofile.io/d/MUET", "nom": "c.rar", "taille": "1 GB",
     "etat": None},
]}}}
cat4 = _cat()
ingerer(cat4, RELEVE_ETAT)
par_url = {l["url"]: l for l in cat4["packages"][0]["downloadLinks"]}
assert not par_url["https://gofile.io/d/VIVANT"].get("linkDead")
assert par_url["https://gofile.io/d/MORT"].get("linkDead") is True
# TEMOIN : un etat ABSENT ne vaut pas « mort ». L absence d information n est
# pas une information — c est le zero rassurant, et il ferait disparaitre des
# liens vivants.
assert not par_url["https://gofile.io/d/MUET"].get("linkDead")


# --- un conteneur dont TOUT est deja la disparait quand meme ----------------
# Le garder au motif qu il n apporte rien de neuf etait un contresens : il
# n heberge aucun fichier, et c est justement quand ses miroirs sont deja
# presents qu il est le plus inutile. Mesure du 2026-08-31 : le run CI
# annonçait « 0 conteneur resolu » alors que 528 liens du releve etaient bien
# dans le catalogue — le conteneur restait a cote d eux, run apres run.
cat5 = _cat()
cat5["packages"][0]["downloadLinks"] += [
    {"url": "https://gofile.io/d/2D3eu3uM"},
    {"url": "https://1fichier.com/?abc&af=1"},
]
s5 = ingerer(cat5, RELEVE)
u5 = [l["url"] for l in cat5["packages"][0]["downloadLinks"]]
assert "https://link-vault.org/c/68tx71hg" not in u5, u5
assert s5["conteneurs_resolus"] == 1 and s5["ajoutes"] == 0, s5
# TEMOIN : rien n a ete duplique au passage
assert u5.count("https://gofile.io/d/2D3eu3uM") == 1, u5

print("OK")
