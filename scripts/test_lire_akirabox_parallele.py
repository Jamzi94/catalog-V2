#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La lecture concurrente pose les MEMES noms que la lecture une-par-une.

Mesure qui a motive le changement : sur le run 33288861281, l etape akirabox a
mis 15 minutes pour 400 pages — une page a la fois, avec cinq instances
FlareSolverr inoccupees a quatre cinquiemes. Le pool est pourtant concurrent
depuis toujours (verrou sur son round-robin) et scrape_superpsx s en sert ainsi.

Ce test ne mesure PAS la vitesse : il tient le contrat qui rend la vitesse sans
danger — meme resultat a un fil et a cinq, et aucun compteur perdu en route.
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lire_akirabox as A                                            # noqa: E402

PAGE = ('<meta property="og:description" content="Download {nom} (2.5 GB) now. '
        'Fast and easy at akirabox.com">')


class FauxPool:
    """Rend une page differente par URL, et compte les appels SIMULTANES."""

    def __init__(self, taille):
        self._taille = taille
        self.max_simultanes = 0
        self._en_cours = 0
        self._v = threading.Lock()

    # PROPRIETE, comme dans flaresolverr_pool. Ce faux objet l'exposait en
    # METHODE : le test passait au vert pendant que la CI mourait sur
    # « 'int' object is not callable ». Un double qui ne copie pas le contrat du
    # vrai objet ne teste que lui-meme.
    @property
    def size(self):
        return self._taille

    def get(self, url):
        with self._v:
            self._en_cours += 1
            self.max_simultanes = max(self.max_simultanes, self._en_cours)
        try:
            # DEFAUT corrige du test : sans ce delai, le faux pool repondait si
            # vite que cinq fils ne se croisaient JAMAIS et max_simultanes
            # restait a 1 — sur du code pourtant bien concurrent. Un temoin de
            # simultaneite ne discrimine que si le travail dure.
            time.sleep(0.05)
            ident = url.rstrip("/").split("/")[-1]
            class R:
                text = PAGE.format(nom=f"Jeu-{ident}.pkg")
            return R()
        finally:
            with self._v:
                self._en_cours -= 1


def _catalogue(n):
    return {"packages": [{"titleId": "PPSA1", "downloadLinks": [
        {"url": f"https://akirabox.com/{i:03d}"} for i in range(n)]}]}


def _run(n, fils, taille_pool):
    faux = FauxPool(taille_pool)
    A._pool = lambda: faux
    with tempfile.TemporaryDirectory() as d:
        cat = Path(d) / "c.json"
        cat.write_text(json.dumps(_catalogue(n)), encoding="utf-8")
        argv = [str(cat), "--pause", "0", "--fils", str(fils)]
        assert A.main(argv) == 0
        liens = json.loads(cat.read_text(encoding="utf-8"))["packages"][0]["downloadLinks"]
    return liens, faux


# --- meme resultat a un fil et a cinq ---------------------------------------
un, pool_un = _run(40, 1, 5)
cinq, pool_cinq = _run(40, 5, 5)
assert [l["fileName"] for l in un] == [l["fileName"] for l in cinq], "resultats divergents"
assert all(l["fileName"] == f"Jeu-{i:03d}.pkg" for i, l in enumerate(cinq)), "noms melanges"
assert all(l["sizeBytes"] == int(2.5 * 1024 ** 3) for l in cinq)

# TEMOIN : les fils ont VRAIMENT tourne de front. Sans lui, ce test passerait
# a l identique sur une version restee sequentielle et ne prouverait rien.
assert pool_cinq.max_simultanes > 1, f"un seul appel a la fois : {pool_cinq.max_simultanes}"
assert pool_un.max_simultanes == 1, f"un fil demande, {pool_un.max_simultanes} obtenus"

# --- le nombre de fils suit la taille du pool quand on ne dit rien -----------
_, p2 = _run(20, 0, 2)
assert p2.max_simultanes <= 2, p2.max_simultanes

print("OK")
