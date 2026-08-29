#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L'abreviation des versions, ecrite AVANT la fonction.

    python scripts/test_versions.py

Regle voulue : la forme la plus courte qui reste NON AMBIGUE parmi les versions
affichees sur la MEME fiche. Une forme qui serait le prefixe d'une autre version
de la fiche est ambigue et doit etre refusee — c'est tout l'interet du
« dynamique selon les versions detectees ».
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pegasus_finalize import abreger_versions  # noqa: E402

# 1) Seule sur sa fiche : on retire les segments de queue nuls et le zero de tete.
assert abreger_versions({"01.200.000"}) == {"01.200.000": "1.200"}
assert abreger_versions({"01.000"}) == {"01.000": "1.000"}

# 2) Deux versions dont l'une prefixe l'autre : la forme courte serait AMBIGUE,
#    on la refuse et on garde de quoi les distinguer.
r = abreger_versions({"01.200.000", "01.200.007"})
assert r["01.200.000"] != r["01.200.007"], r
assert not r["01.200.000"].startswith(r["01.200.007"]), r
assert "200" in r["01.200.007"] and "007" in r["01.200.007"], r

# 3) Versions franchement differentes : chacune peut etre abregee de son cote.
r = abreger_versions({"01.000", "02.030"})
assert r == {"01.000": "1.000", "02.030": "2.030"}, r

# 4) Temoin negatif : on n'abrege JAMAIS au point de rendre deux versions
#    identiques.
r = abreger_versions({"01.000", "1.000"})
assert len(set(r.values())) == 2, r

# 5) Temoin negatif : ce qui est deja minimal ne bouge pas.
assert abreger_versions({"1.05"}) == {"1.05": "1.05"}

# 6) Une version a un seul segment reste entiere (rien a retirer sans mentir).
assert abreger_versions({"1.0"}) == {"1.0": "1.0"}

# 7) Ensemble vide, et valeurs vides : pas de plantage.
assert abreger_versions(set()) == {}
assert abreger_versions({""}) == {"": ""}

print("OK")
