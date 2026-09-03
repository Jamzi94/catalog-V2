#!/usr/bin/env python3
"""
Sondage de la taille d'un fichier chez les hébergeurs (sizeBytes exact).
=======================================================================
Beaucoup de pages dlpsgame/superpsx n'annoncent pas la taille en texte. On la
récupère alors directement auprès de l'hébergeur, en octets exacts, SANS
télécharger le fichier.

Hébergeurs implémentés (recettes vérifiées, sans clé / friction minimale) :
  - vikingfile.com : POST /api/check-files (hash) -> size   [CANDIDAT #1, batch]
  - mega.nz        : POST g.api.mega.co.nz/cs cmd 'g' -> 's' (octets)
  - gofile.io      : token invité + wt -> GET /contents -> size (ou somme)

Les autres hôtes (akirabox, mediafire, datanodes, buzzheavier, datavaults,
filekeeper, rootz, 1cloudfile, 1fichier) nécessitent soit une clé API, soit du
parsing HTML derrière Cloudflare (JA3) — non implémentés ici pour ne pas écrire
de tailles non fiables. Le point d'extension `RESOLVERS` permet de les ajouter.

API : probe_size(url) -> int | None  (octets).
Le transport HTTP est injectable (`fetcher=`) pour tester sans réseau et pour
router via curl/FlareSolverr en CI si besoin.

CLI :
  python hoster_size.py "https://vikingfile.com/f/HASH"
  python hoster_size.py --catalog ps5-catalog.json --max 300   # remplit sizeBytes manquants
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = "dlpsgame-pegasus-size/1.0"
HTTP_TIMEOUT = 25
CACHE_DIR = Path(".scrape_cache_sizes")

# Version des SONDES. A incrementer des qu'une sonde change de facon de
# mesurer. Le cache garde aussi bien une taille qu'un None, et un None cache par
# une sonde aveugle est indistinguable d'un « vraiment insondable » : c'est ce
# qui s'est passe pour vikingfile, dont la sonde interrogeait une API disparue.
# Le correctif serait reste inerte sur les 3623 liens deja caches.
# 2 : vikingfile lit desormais la page (id="size") et reconnait vik1ngfile.site.
SONDE_VERSION = 2
CACHE_ENABLED = True
MAX_SANE_BYTES = 900 * 1024 ** 3  # garde-fou : > 900 Go = aberrant (cf. pegasus_finalize)

# Hôtes que l'on sait sonder (cf. RESOLVERS). Un jeu sans aucun de ces miroirs
# est « insondable » : inutile de l'inclure dans le budget --max.
# vik1ngfile.site : le site a change de domaine, l ancien redirige. Sans cette
# entree, les 3623 liens vikingfile — premier hebergeur du catalogue — etaient
# declares insondables alors que la page annonce sa taille en clair.
PROBEABLE_HOSTS = ("vikingfile.com", "vik1ngfile.site", "mega.nz", "mega.co.nz",
                   "gofile.io", "mediafire.com", "www.mediafire.com")

# TTL (jours) de ré-essai pour un jeu sondé SANS succès : on évite de re-sonder
# en boucle les ~49 insondables à chaque run.
PROBE_RETRY_TTL_DAYS = 14


# ---------------------------------------------------------------------------
# Transport HTTP (injectable)
# ---------------------------------------------------------------------------
def _default_fetch(url: str, *, method: str = "GET", data: bytes | None = None,
                   headers: dict | None = None, timeout: int = HTTP_TIMEOUT) -> tuple[int, bytes]:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        try:
            return exc.code, exc.read()
        except Exception:
            return exc.code, b""


# Le fetcher courant (remplaçable pour tests / curl / FlareSolverr).
_FETCH = _default_fetch


def set_fetcher(fn) -> None:
    global _FETCH
    _FETCH = fn


# ---------------------------------------------------------------------------
# Cache disque
# ---------------------------------------------------------------------------
def _cache_get(url: str) -> int | None | bool:
    """Renvoie la taille cachée, None (sondé sans succès) ou False (absent du cache)."""
    if not CACHE_ENABLED:
        return False
    f = CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")
    if f.exists():
        try:
            donnee = json.loads(f.read_text())
        except Exception:
            return False
        # Ecrit par une sonde anterieure : on ne peut pas savoir si son None
        # etait un « insondable » ou un « je n'ai pas su regarder ». On re-sonde.
        if donnee.get("sonde") != SONDE_VERSION:
            return False
        return donnee.get("size")
    return False


def _cache_set(url: str, size: int | None) -> None:
    if not CACHE_ENABLED:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")
        f.write_text(json.dumps({"url": url, "size": size, "sonde": SONDE_VERSION}))
    except Exception:
        pass


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _sane(size) -> int | None:
    # Plusieurs hébergeurs (vikingfile, mediafire…) renvoient la taille en
    # CHAÎNE ("1073741824") : on coerce les chaînes purement numériques, sinon
    # on rejetait des tailles pourtant valides (cause de jeux « sans taille »).
    if isinstance(size, bool):
        return None
    if isinstance(size, str):
        s = size.strip()
        if not re.fullmatch(r"\d+", s):
            return None
        size = int(s)
    if not isinstance(size, (int, float)):
        return None
    size = int(size)
    return size if 0 < size <= MAX_SANE_BYTES else None


# ---------------------------------------------------------------------------
# vikingfile.com — POST /api/check-files (hash) -> size  (sans clé)
# ---------------------------------------------------------------------------
def _size_vikingfile(url: str) -> int | None:
    """Taille lue sur la PAGE du fichier.

    L'ancienne sonde interrogeait POST vikingfile.com/api/check-files et ne
    reconnaissait que le domaine .com. Le site a bascule sur vik1ngfile.site :
    elle rendait None sur les 3623 liens vikingfile du catalogue — premier
    hebergeur — et le lien etait classe « insondable » alors que l'instrument
    etait simplement aveugle. Un None n'est pas une mesure.

    La page porte la taille dans un bloc dedie :
        <div id="file-information">
          <h2 id="filename">PPSA31246.exfat</h2>
          <p id="size">121.09 GB</p>
        </div>
    On vise CE bloc et pas le premier nombre venu : la page contient aussi des
    « 70KB », « 4MB » et « 20GB » dans son script obfusque et ses encarts. Le
    test le verifie sur une page reelle.
    """
    if not re.search(r"vik(?:ing|1ng)file\.(?:com|site)/(?:f|d)/", url):
        return None
    try:
        status, raw = _FETCH(url)
    except Exception:                                        # noqa: BLE001
        return None
    if status != 200:
        return None
    page = raw.decode("utf-8", "replace")
    m = re.search(r"id=.size.[^>]*>\s*([\d.,]+)\s*([KMGT]?i?B)", page, re.I)
    if not m:
        return None
    nombre = m.group(1).replace(",", "")
    unite = m.group(2).upper().replace("I", "")
    facteurs = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    try:
        return _sane(int(float(nombre) * facteurs.get(unite, 1)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# mega.nz — POST g.api.mega.co.nz/cs cmd 'g' -> 's' (octets)
# ---------------------------------------------------------------------------
def _size_mega(url: str) -> int | None:
    # Formats : https://mega.nz/file/<ID>#<KEY>  ou ancien  /#!<ID>!<KEY>
    m = re.search(r"mega\.(?:nz|co\.nz)/file/([A-Za-z0-9_-]+)", url) \
        or re.search(r"mega\.(?:nz|co\.nz)/#!([A-Za-z0-9_-]+)", url)
    if not m:
        return None
    file_id = m.group(1)
    body = json.dumps([{"a": "g", "p": file_id}]).encode()
    status, raw = _FETCH("https://g.api.mega.co.nz/cs?id=0", method="POST",
                         data=body, headers={"Content-Type": "application/json"})
    if status != 200:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    # Réponse normale : [{"s": <octets>, ...}] ; erreur : un entier négatif.
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _sane(data[0].get("s"))
    return None


# ---------------------------------------------------------------------------
# gofile.io — token invité + wt -> GET /contents -> size (ou somme du dossier)
# ---------------------------------------------------------------------------
_GOFILE_WT_RE = re.compile(r"""wt['"]?\s*[:=]\s*['"]([\w-]{4,})['"]""")


def _size_gofile(url: str) -> int | None:
    m = re.search(r"gofile\.io/(?:d|w)/([A-Za-z0-9]+)", url)
    if not m:
        return None
    code = m.group(1)
    # 1) token invité
    status, raw = _FETCH("https://api.gofile.io/accounts", method="POST",
                         data=b"", headers={"Content-Type": "application/json"})
    if status != 200:
        return None
    try:
        token = json.loads(raw.decode("utf-8", "replace")).get("data", {}).get("token")
    except Exception:
        token = None
    if not token:
        return None
    # 2) wt depuis global.js
    status, raw = _FETCH("https://gofile.io/dist/js/global.js")
    wt = None
    if status == 200:
        mm = _GOFILE_WT_RE.search(raw.decode("utf-8", "replace"))
        wt = mm.group(1) if mm else None
    if not wt:
        return None
    # 3) contents
    status, raw = _FETCH(f"https://api.gofile.io/contents/{code}?wt={wt}",
                         headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace")).get("data", {})
    except Exception:
        return None
    if data.get("size") is not None:
        return _sane(data.get("size"))
    # dossier : somme des enfants fichiers
    children = data.get("children") or {}
    if isinstance(children, dict) and children:
        total = sum(int(c.get("size") or 0) for c in children.values() if isinstance(c, dict))
        return _sane(total)
    return None


# ---------------------------------------------------------------------------
# mediafire.com — API publique get_info (quick_key) -> file_info.size (octets)
# ---------------------------------------------------------------------------
def _size_mediafire(url: str) -> int | None:
    # Formats : mediafire.com/file/<quick_key>/<nom>/file  ou  mediafire.com/?<quick_key>
    m = re.search(r"mediafire\.com/file/([A-Za-z0-9]+)", url) \
        or re.search(r"mediafire\.com/\?([A-Za-z0-9]+)", url)
    if not m:
        return None  # dossiers (/folder/) non gérés ici -> insondable proprement
    quick_key = m.group(1)
    api = ("https://www.mediafire.com/api/1.5/file/get_info.php"
           f"?quick_key={urllib.parse.quote(quick_key)}&response_format=json")
    status, raw = _FETCH(api)
    if status != 200:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    # {"response":{"result":"Success","file_info":{"size":"123456", ...}}}
    info = (data.get("response") or {}).get("file_info") or {}
    return _sane(info.get("size"))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
RESOLVERS = [
    ("vikingfile", _size_vikingfile),
    ("mega", _size_mega),
    ("gofile", _size_gofile),
    ("mediafire", _size_mediafire),
]

# Priorité de fiabilité quand un jeu a plusieurs miroirs.
_HOST_PRIORITY = ["vikingfile.com", "mega.nz", "mega.co.nz", "gofile.io",
                  "mediafire.com", "www.mediafire.com"]


_ACCUEILS = {"datanodes.to": "https://datanodes.to/",
             "filekeeper.net": "https://filekeeper.net/",
             # datavaults sert la meme page que datanodes (og:title « nom (taille) »)
             "datavaults.co": "https://datavaults.co/",
             # buzzheavier n'exige pas de session : le titre EST le nom, et la
             # taille suit « Download File ». Une page morte y rend 404 avec
             # « Whatever lived here has returned to the void » — c'est un
             # fichier disparu, pas un blocage, et il faut le dire ainsi.
             "buzzheavier.com": "https://buzzheavier.com/"}


def _page_avec_session(url: str) -> str | None:
    """Page du fichier, obtenue comme le fait un navigateur.

    Une requete nue rend 404 sur datanodes.to et filekeeper.net — 8 liens sur 8
    testes le 2026-08-30, ce qui laissait croire que 1793 liens du catalogue
    etaient morts. Ils ne le sont pas : c'est une defense anti-robot. Il suffit
    d'ouvrir l'accueil pour recevoir le cookie de session, puis de demander le
    fichier avec ce cookie — exactement ce que fait le navigateur, verifie a
    l'identique via Playwright avant d'ecrire ceci.
    """
    import http.cookiejar
    import urllib.request as _u
    hote = _host(url)
    accueil = _ACCUEILS.get(hote)
    if not accueil:
        return None
    entetes = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
               ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8"),
               ("Accept-Language", "fr-FR,fr;q=0.9,en;q=0.8")]
    try:
        jar = http.cookiejar.CookieJar()
        op = _u.build_opener(_u.HTTPCookieProcessor(jar))
        op.addheaders = entetes
        with op.open(accueil, timeout=HTTP_TIMEOUT) as r:
            r.read(1000)
        with op.open(url, timeout=HTTP_TIMEOUT) as r:
            return r.read(300000).decode("utf-8", "replace")
    except Exception:                                        # noqa: BLE001
        return None


def _octets(nombre: str, unite: str) -> int | None:
    facteurs = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    try:
        return int(float(nombre.replace(",", "")) * facteurs[unite.upper().replace("I", "")])
    except (ValueError, KeyError):
        return None


def nom_et_taille(url: str) -> tuple:
    """(nom de fichier, octets) pour les hotes lisibles par session, sinon (None, None).

    Les deux hotes exposent l'information a un endroit STABLE et sans ambiguite :
      datanodes  : <meta property="og:title" content="PPSA01500.7z (67.3 GB)">
      filekeeper : <title>Telechargement ...</title> + un span de taille
    On vise ces ancres et pas le premier nombre venu : les deux pages portent
    par ailleurs des tailles d'encart (« 870 KB », « 5 TB »), et une lecture
    gloutonne rendrait un chiffre plausible et faux.
    """
    hote = _host(url)
    if hote not in _ACCUEILS:
        return (None, None)
    page = _FETCH_SESSION(url)
    if not page:
        return (None, None)
    # Recherche par chaine litterale, sans regex : les guillemets HTML se
    # melent mal aux echappements, et ces ancres sont fixes.
    marque = "og:title" + chr(34) + " content=" + chr(34)
    i = page.find(marque)
    if i >= 0:
        j = page.find(chr(34), i + len(marque))
        og = page[i + len(marque):j] if j > 0 else ""
        mm = re.match(r"^(.*?)[ ]*\(([0-9.,]+)[ ]*([KMGT]?i?B)\)[ ]*$", og)
        if mm:
            return (mm.group(1).strip(), _octets(mm.group(2), mm.group(3)))
    # buzzheavier : le titre porte le nom, « Download File 40.4GB » la taille.
    if hote == "buzzheavier.com":
        mt_ = re.search(r"<title>([^<]{3,120})</title>", page)
        nom_ = mt_.group(1).strip() if mt_ else ""
        mz_ = re.search(r"class=.size.>([0-9][0-9.,]*) *([KMGT]i?B)", page)
        if nom_ and "buzzheavier" not in nom_.lower():
            return (nom_, _octets(mz_.group(1), mz_.group(2)) if mz_ else None)
        return (None, None)
    # datavaults : le nom vit dans un champ cache « fname ». Sa page n'affiche
    # AUCUNE taille de fichier — les « 1 GB » et « 15 GB » qu'on y lit sont les
    # limites de l'offre (Max upload, Storage space, Download volume). Les
    # prendre pour la taille du fichier serait un chiffre plausible et faux :
    # on rend donc le nom et rien d'autre.
    if hote == "datavaults.co":
        marque3 = "name=" + chr(34) + "fname" + chr(34) + " value=" + chr(34)
        i3 = page.find(marque3)
        if i3 >= 0:
            j3 = page.find(chr(34), i3 + len(marque3))
            nom3 = page[i3 + len(marque3):j3] if j3 > 0 else ""
            if nom3:
                return (nom3, None)
        return (None, None)
    marque2 = "id=" + chr(34) + "dl-filename" + chr(34)
    i = page.find(marque2)
    if i >= 0:
        j = page.find(">", i)
        k = page.find("<", j + 1)
        nom = page[j + 1:k].strip() if j > 0 and k > j else ""
        # La taille suit le nom dans le document ; on cherche a partir de la
        # pour ne pas ramasser les tailles d encart plus bas (« 5 TB »).
        mt = re.search(r"([0-9][0-9.,]*) *([KMGT]i?B)", page[i:i + 4000])
        if nom:
            return (nom, _octets(mt.group(1), mt.group(2)) if mt else None)
    return (None, None)


def _FETCH_SESSION(url: str):
    return _page_avec_session(url)


def probe_size(url: str) -> int | None:
    """Renvoie la taille (octets) du fichier derrière `url`, ou None."""
    if not url:
        return None
    cached = _cache_get(url)
    if cached is not False:
        return cached  # int ou None déjà connu
    size = None
    for _, resolver in RESOLVERS:
        try:
            size = resolver(url)
        except Exception:
            size = None
        if size:
            break
    _cache_set(url, size)
    return size


def _package_urls(pkg: dict) -> list[str]:
    links = pkg.get("downloadLinks") or []
    return [l.get("url") for l in links if isinstance(l, dict) and l.get("url")]


def has_probeable_mirror(pkg: dict) -> bool:
    """Le package a-t-il au moins un miroir vikingfile/mega/gofile ?

    Un jeu sans aucun de ces hôtes est insondable : on le saute d'emblée et on
    ne le compte PAS dans le budget --max."""
    for u in _package_urls(pkg):
        if _host(u) in PROBEABLE_HOSTS:
            return True
    return False


def _probed_recently(pkg: dict, ttl_days: int) -> bool:
    """Le package a-t-il été sondé-sans-succès il y a moins de ttl_days jours ?

    S'appuie sur `_sizeProbedAt` (timestamp ISO). Permet d'exclure pendant un TTL
    les jeux insondables déjà tentés (évite de re-sonder en boucle)."""
    if ttl_days <= 0:
        return False
    ts = pkg.get("_sizeProbedAt")
    if not ts:
        return False
    try:
        when = dt.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - when) < dt.timedelta(days=ttl_days)


def probe_package_size(pkg: dict) -> int | None:
    """Sonde la taille via les downloadLinks d'un package (miroirs fiables d'abord)."""
    urls = _package_urls(pkg)

    def rank(u: str) -> int:
        h = _host(u)
        return _HOST_PRIORITY.index(h) if h in _HOST_PRIORITY else len(_HOST_PRIORITY)

    for u in sorted(urls, key=rank):
        size = probe_size(u)
        if size:
            return size
    return None


# ---------------------------------------------------------------------------
# Batch : remplir les sizeBytes manquants d'un catalogue
# ---------------------------------------------------------------------------
def fill_missing_sizes(catalog: dict, *, max_probe: int = 0, delay: float = 0.3,
                       concurrency: int = 6, retry_ttl_days: int = PROBE_RETRY_TTL_DAYS) -> dict:
    stats = {"total": 0, "already": 0, "probed": 0, "filled": 0,
             "skipped_nomirror": 0, "skipped_ttl": 0}
    pkgs = catalog.get("packages", [])
    stats["total"] = len(pkgs)

    # Présélection mono-thread (déterministe) : on filtre les jeux à sonder et on
    # applique le budget --max AVANT de paralléliser.
    #  - sizeBytes déjà connu  -> déjà
    #  - aucun miroir sondable -> sauté (NON compté dans le budget)
    #  - sondé-sans-succès récemment -> exclu pendant le TTL
    todo: list[dict] = []
    for pkg in pkgs:
        if pkg.get("sizeBytes"):
            stats["already"] += 1
            continue
        if not has_probeable_mirror(pkg):
            stats["skipped_nomirror"] += 1
            continue
        if _probed_recently(pkg, retry_ttl_days):
            stats["skipped_ttl"] += 1
            continue
        if max_probe and len(todo) >= max_probe:
            continue
        todo.append(pkg)

    if not todo:
        return stats

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    workers = max(1, concurrency)

    def _do(pkg: dict) -> tuple[dict, int | None]:
        # Jitter pour rester poli (pas de rate-limit strict côté hébergeurs).
        time.sleep(random.uniform(0.1, 0.3))
        try:
            return pkg, probe_package_size(pkg)
        except Exception:  # noqa: BLE001
            return pkg, None

    if workers <= 1:
        results_iter = (_do(p) for p in todo)
    else:
        pool = cf.ThreadPoolExecutor(max_workers=workers)
        results_iter = pool.map(_do, todo)

    # Consommation mono-thread des résultats (mutation pkg + stats sûre).
    for pkg, size in results_iter:
        stats["probed"] += 1
        if size:
            pkg["sizeBytes"] = int(size)
            stats["filled"] += 1
            pkg.pop("_sizeProbedAt", None)  # succès : on efface le marqueur d'échec
        else:
            # Marque le jeu sondé-sans-succès pour l'exclure pendant le TTL.
            pkg["_sizeProbedAt"] = now_iso

    if workers > 1:
        pool.shutdown(wait=True)
    return stats


def _grappe(link: dict) -> tuple:
    return (link.get("group"), link.get("version"),
            link.get("region"), link.get("editionId"))


def fill_link_sizes(catalog: dict, *, max_probe: int = 0, delay: float = 0.3,
                    seulement_bp: bool = True) -> dict:
    """Sonde UNE taille par rubrique et la pose sur le lien sonde.

    UNE SONDE PAR LIEN, et non plus une par rubrique. L'economie reposait sur
    « une rubrique = un fichier » : le temoin l'a tuee. En sondant un second
    miroir de 61 rubriques deja mesurees, 53 rendent une taille DIFFERENTE et 15
    changent de classement — un lien Mediafire de 43 Mo avait herite de 39,7 Go.
    Tant que le libelle brut de la rubrique n'est pas stocke, aucune cle ne
    regroupe fiablement des miroirs. On paie donc une requete par lien : 1227
    liens BP sondables sur ce catalogue, UNE fois, puis le cache disque les
    ressert (SONDE_VERSION invalide quand la sonde change).

    Pourquoi seulement les BP : c'est la ou la taille TRANCHE. Un lien « BP »
    est tantot le jeu repackage, tantot le seul binaire a deposer dans le
    dossier — mesure du 2026-08-30 : 49 liens sous 100 Mo contre 58 au-dessus de
    1 Go, et un seul dans la vallee. Ailleurs, la taille n'apprend rien que la
    fiche ne dise deja. 953 rubriques BP a sonder sur ce catalogue, une fois,
    puis le cache disque les ressert.
    """
    stats = {"rubriques": 0, "sondees": 0, "trouvees": 0, "budget": max_probe}
    for pkg in catalog.get("packages", []):
        liens = [l for l in (pkg.get("downloadLinks") or []) if isinstance(l, dict)]
        for link in liens:
            if seulement_bp and "BP" not in (link.get("name") or ""):
                continue
            stats["rubriques"] += 1
            if link.get("sizeBytes"):
                continue
            if _host(link.get("url", "")) not in PROBEABLE_HOSTS:
                continue
            if max_probe and stats["sondees"] >= max_probe:
                continue
            stats["sondees"] += 1
            taille = probe_size(link["url"])
            if taille:
                link["sizeBytes"] = taille
                stats["trouvees"] += 1
            if delay:
                time.sleep(delay)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="URL d'un fichier à sonder")
    ap.add_argument("--catalog", type=Path, help="Catalogue : remplir les sizeBytes manquants")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max", type=int, default=0, help="Nb max de jeux à sonder (0 = tous)")
    ap.add_argument("--concurrency", type=int, default=6,
                    help="Nb de threads de sondage parallèles (défaut 6)")
    ap.add_argument("--retry-ttl-days", type=int, default=PROBE_RETRY_TTL_DAYS,
                    help=f"TTL (jours) avant de re-sonder un jeu sans succès "
                         f"(défaut {PROBE_RETRY_TTL_DAYS} ; 0 = re-sonder à chaque run)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    global CACHE_ENABLED
    if args.no_cache:
        CACHE_ENABLED = False

    if args.catalog:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        stats = fill_missing_sizes(catalog, max_probe=args.max,
                                   concurrency=args.concurrency,
                                   retry_ttl_days=args.retry_ttl_days)
        out = args.out or args.catalog
        out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Tailles : {stats['total']} jeux | {stats['already']} déjà connues | "
              f"{stats['probed']} sondés | {stats['filled']} complétés | "
              f"{stats['skipped_nomirror']} sans miroir sondable | "
              f"{stats['skipped_ttl']} exclus (TTL ré-essai)")
        return 0

    if args.url:
        size = probe_size(args.url)
        print(f"{args.url} -> {size} octets" if size else f"{args.url} -> taille inconnue")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
