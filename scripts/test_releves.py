#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relevés séparés puis appliqués : la panne qu'on veut rendre impossible.

Deux collectes qui réécrivent le même catalogue en parallèle produisent un
fichier VALIDE dont la moitié du travail a disparu. Aucune exception, aucun
JSON cassé, rien à voir dans le journal. Ce test tient le contrat qui
l'empêche : deux relevés disjoints se retrouvent TOUS LES DEUX à l'arrivée.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from releves import appliquer, ecrire                                # noqa: E402

Go = 1024 ** 3


def _catalogue():
    return {"packages": [
        {"titleId": "PPSA00001", "downloadLinks": [
            {"url": "https://datanodes.to/f/aaa"},
            {"url": "https://akirabox.com/xyz"},
            {"url": "https://link-vault.org/zzz"},
        ]},
        # Le meme miroir sur une SECONDE fiche : un releve doit nommer les deux.
        {"titleId": "PPSA00002", "downloadLinks": [
            {"url": "https://datanodes.to/f/aaa"},
            {"url": "https://vikingfile.com/bbb", "fileName": "deja-nomme.rar"},
        ]},
    ]}


# --- LE CONTRAT : deux collectes simultanees, aucune ne perd son travail -----
cat = _catalogue()
lisibles = {"https://datanodes.to/f/aaa": {"fileName": "GameA.EUR.pkg",
                                           "sizeBytes": 40 * Go}}
akirabox = {"https://akirabox.com/xyz": {"fileName": "GameB.DLC.rar"}}
# DEFAUT du test, corrige : deux occurrences de l'URL x deux champs = 4.
assert appliquer(cat, lisibles) == 4, "2 occurrences x (fileName + sizeBytes)"
assert appliquer(cat, akirabox) == 1
liens = [l for p in cat["packages"] for l in p["downloadLinks"]]
noms = {l["url"]: l.get("fileName") for l in liens}
assert noms["https://datanodes.to/f/aaa"] == "GameA.EUR.pkg"
assert noms["https://akirabox.com/xyz"] == "GameB.DLC.rar", "le second releve a ete efface"

# TEMOIN NEGATIF : sans le second appel, akirabox n'est PAS nomme. Si ce
# temoin passait, le test ci-dessus ne prouverait rien — il verrait un nom
# qu'un autre chemin aurait pose.
temoin = _catalogue()
appliquer(temoin, lisibles)
assert all(l.get("fileName") is None
           for p in temoin["packages"] for l in p["downloadLinks"]
           if l["url"] == "https://akirabox.com/xyz")

# --- le catalogue a raison contre un releve ---------------------------------
cat2 = _catalogue()
assert appliquer(cat2, {"https://vikingfile.com/bbb": {"fileName": "AUTRE.rar"}}) == 0
assert cat2["packages"][1]["downloadLinks"][1]["fileName"] == "deja-nomme.rar"

# --- une URL inconnue ne cree pas de lien fantome ----------------------------
cat3 = _catalogue()
avant = sum(len(p["downloadLinks"]) for p in cat3["packages"])
assert appliquer(cat3, {"https://inconnu.example/1": {"fileName": "x.rar"}}) == 0
assert sum(len(p["downloadLinks"]) for p in cat3["packages"]) == avant

# --- ecrire ne retient QUE ce qui a ete nomme --------------------------------
with tempfile.TemporaryDirectory() as d:
    chemin = Path(d) / "r.json"
    n = ecrire(chemin, [
        {"url": "https://a/1", "fileName": "ok.rar", "sizeBytes": 12},
        {"url": "https://a/2"},                       # rien releve : ignore
        {"url": "https://a/3", "sizeBytes": 99},      # taille sans nom : ignore
    ])
    assert n == 1, n
    dedans = json.loads(chemin.read_text(encoding="utf-8"))
    assert dedans == {"https://a/1": {"fileName": "ok.rar", "sizeBytes": 12}}, dedans

print("OK")
