#!/usr/bin/env python3
"""Extrait un mini-catalogue de test à partir du catalogue complet.

Sert à donner à un client un fichier léger, valide et immédiatement
testable : même structure que le catalogue de production, mais quelques
jeux seulement, choisis parmi les plus PETITS pour qu'un téléchargement de
bout en bout reste rapide.

Usage :
  python3 scripts/build_test_catalog.py ps5-catalog.json --out demo-3-games.json
  python3 scripts/build_test_catalog.py catalogue.json --count 3 --seed 42
  python3 scripts/build_test_catalog.py --self-test
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# On tire au sort parmi les N plus petits plutôt que de prendre les N plus
# petits : la sélection change d'un run à l'autre (donc le fichier de test ne
# fige pas les trois mêmes jeux à vie) tout en restant légère.
POOL_SIZE = 40


def eligible(pkg: dict) -> bool:
    """Un jeu utilisable comme cas de test.

    Exige une taille connue ET au moins un lien : un paquet sans lien ne
    permet de tester ni le téléchargement ni l'affichage des hébergeurs.
    """
    return bool(pkg.get("sizeBytes")) and bool(pkg.get("downloadLinks"))


def pick(packages: list[dict], count: int, rng: random.Random) -> list[dict]:
    """`count` jeux tirés au sort parmi les `POOL_SIZE` plus petits éligibles."""
    ok = sorted((p for p in packages if eligible(p)), key=lambda p: p["sizeBytes"])
    pool = ok[:POOL_SIZE]
    if len(pool) <= count:
        return pool
    return rng.sample(pool, count)


def build(catalog: dict, count: int, rng: random.Random) -> dict:
    chosen = pick(catalog.get("packages") or [], count, rng)
    return {
        "name": f"{catalog.get('name') or 'Catalogue'} — TEST ({len(chosen)} jeux)",
        "version": catalog.get("version", 1),
        "packages": chosen,
    }


def _self_test() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        ok = ok and cond

    lien = [{"name": "Akia", "url": "https://example.invalid/x"}]
    cat = {"name": "C", "version": 1, "packages": [
        {"title": f"J{i}", "sizeBytes": (i + 1) * 10**9, "downloadLinks": lien}
        for i in range(60)
    ] + [
        {"title": "sans-taille", "downloadLinks": lien},           # inéligible
        {"title": "sans-lien", "sizeBytes": 1},                     # inéligible
    ]}
    out = build(cat, 3, random.Random(1))
    check(f"{len(out['packages'])} jeux retenus", len(out["packages"]) == 3)
    check("tous eligibles (taille + liens)", all(eligible(p) for p in out["packages"]))
    check("aucun paquet sans taille", all(p.get("sizeBytes") for p in out["packages"]))
    gros = max(p["sizeBytes"] for p in out["packages"])
    check(f"pris parmi les {POOL_SIZE} plus petits (max {gros/10**9:.0f} Go <= {POOL_SIZE} Go)",
          gros <= POOL_SIZE * 10**9)
    check("structure de catalogue valide", set(out) == {"name", "version", "packages"})
    # Témoin : deux graines différentes ne donnent pas la même sélection.
    a = [p["title"] for p in build(cat, 3, random.Random(1))["packages"]]
    b = [p["title"] for p in build(cat, 3, random.Random(2))["packages"]]
    check(f"le tirage varie selon la graine ({a} vs {b})", a != b)
    # Témoin inverse : même graine -> même sélection (reproductible si besoin).
    check("meme graine -> meme selection", a == [p["title"] for p in build(cat, 3, random.Random(1))["packages"]])
    # Cas limite : moins de jeux que demandé.
    petit = build({"packages": [{"title": "seul", "sizeBytes": 1, "downloadLinks": lien}]}, 3, random.Random(1))
    check("catalogue plus petit que --count : pas d'erreur", len(petit["packages"]) == 1)

    print("ALL OK" if ok else "SOME FAILURES")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if (sys.argv[1:] if argv is None else argv)[:1] == ["--self-test"]:
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("catalog", type=Path, help="Catalogue complet en entrée")
    ap.add_argument("--out", type=Path, default=Path("demo-3-games.json"))
    ap.add_argument("--count", type=int, default=3, help="Nombre de jeux (défaut 3)")
    ap.add_argument("--seed", type=int, default=None,
                    help="Graine du tirage (défaut : aléatoire à chaque run)")
    args = ap.parse_args(argv)

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    out = build(catalog, args.count, random.Random(args.seed))
    if not out["packages"]:
        print("Aucun jeu éligible (taille + liens) — fichier de test non écrit.", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Catalogue de test écrit : {args.out} ({args.out.stat().st_size/1024:.1f} Ko)")
    for p in out["packages"]:
        print(f"  - {p['title']}  {p.get('sizeBytes', 0)/2**30:.2f} Go  "
              f"{len(p.get('downloadLinks') or [])} liens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
