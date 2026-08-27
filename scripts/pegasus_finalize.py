#!/usr/bin/env python3
"""
Finalisation + validation d'un catalogue pour Pegasus DL.
==========================================================
Étape unique de fin de pipeline (idempotente), exécutée après fusion +
enrichissements. Elle :

  1. Assainit `sizeBytes` : retire toute valeur <= 0 ou aberrante (> 2 To,
     filet de sécurité contre le bug « to » résiduel). Un sizeBytes inconnu
     est OMIS (jamais null/0). NB : `sizeBytes` est un champ OPTIONNEL de
     Pegasus DL — son absence ne fait PAS ignorer le jeu (contrairement à une
     croyance répandue ; seuls titleId/title/downloadLinks[].url sont requis).
  2. Canonicalise `fileFormat` via le module formats (libellés stables).
  3. SURFACE le format dans des champs visibles : ajoute `formatLabel`
     (ex. « FPKG · Backport 4.xx ») et préfixe la description d'une ligne
     « Format: … » (visible dans la vue détail Pegasus).
  4. Valide les champs requis Pegasus et nettoie les downloadLinks invalides
     (URL vide ou non http). Rapporte un résumé ; en --strict, sort != 0 si
     des jeux n'ont aucun lien valide.

Usage :
  python pegasus_finalize.py ps5-catalog.json
  python pegasus_finalize.py in.json --out out.json --strict
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
import unicodedata
from urllib.parse import unquote, urlparse

from formats import display_label, normalize_formats

# Link-lockers : page intermédiaire protégée par CAPTCHA (filecrypt) ou
# raccourcisseur monétisé pointant dessus (shrinkearn/clk). Ne donnent PAS un
# lien direct vers l'hébergeur -> on les retire (sauf si seuls liens du jeu).
_LOCKER_HOSTS = {
    "filecrypt.cc", "filecrypt.co", "filecrypt.to",
    "shrinkearn.com", "clk.sh", "ouo.io", "linkvertise.com",
    # Link-Lock du site exFAT : une page HTML qui ne révèle l'URL réelle qu'en
    # exécutant du JS. import_exfat.py la résout désormais (les deux schémas,
    # mot de passe public « pippo »), donc un lien qui porte ENCORE cet hôte est
    # soit un résidu d'avant le correctif, soit un déchiffrement échoué : dans
    # les deux cas il téléchargerait une page web, pas un jeu. Le retirer
    # supprime aussi les doublons « chiffré + déchiffré » du même fichier, que
    # merge_links() ne peut pas voir puisqu'il dédoublonne par chaîne d'URL.
    "pippo26442999.github.io",
}

# Garde-fou : aucun jeu PS5 réel n'approche 900 Go (le SSD console fait 825 Go).
# Le bug historique « to » produit toujours des tailles >= 1 To ("1 to"=1 To,
# "2 to"=2 To…), donc 900 Go sépare proprement le réel des artefacts.
MAX_SANE_BYTES = 900 * 1024 ** 3
REAL_TITLEID_RE = re.compile(r"^[A-Z]{4}\d{3,}$")

# Marque unique exposée dans le JSON : on masque les vraies sources
# (dlpsgame/superpsx/exFAT) pour TOUS les jeux.
BRAND = "Phoenix DL"
# IMPORTANT : l'app affiche la SOURCE PAGE comme le HOSTNAME de cette URL. Un
# hostname ne peut pas contenir d'espace/majuscule, donc downloadSource DOIT
# être une URL valide -> l'app montrera « phoenixdl.com ». (Un texte brut comme
# « Phoenix DL » est interprété en URL relative et retombe sur l'IP de l'appareil.)
BRAND_SOURCE_URL = "https://phoenixdl.com"


# Conteneurs (pas un format de jeu) et libellés de section (axe orthogonal).
_CONTAINER_FMT = {"rar", "zip", "7z", "iso", "tar", "gz", "part"}

# Priorité d'affichage des formats de base : ce qui dit le TYPE du paquet
# d'abord, ce qui n'est qu'une modalité de livraison ensuite.
_BASE_FMT_ORDER = {"pkg": 0, "fpkg": 0, "apr-emu": 1, "folder": 10}

# « Backport - Viki », « DLC - Data », « Backport 4.xx - Akia »… : préfixe de
# section écrit dans le nom par les anciennes versions des scrapers. La section
# est désormais portée par le champ `group` et affichée dans l'étiquette [...].
_SECTION_PREFIX_RE = re.compile(
    r"^(?:Backport(?:\s+\d\.xx)?|DLC|Dump|Fix|exFAT|Standard)\s*-\s*", re.IGNORECASE
)

# Segments d'attribution repris des pages sources (« Credits: … », « Thanks: … »).
# Ils sont retirés de la description publiée : ce catalogue ne relaie pas ces
# mentions. Appliqué à la finalisation, donc les descriptions déjà en base sont
# nettoyées au run suivant, pas seulement les nouvelles.
_CREDITS_SEG_RE = re.compile(r"^\s*(?:credits?|thanks?|thx)\s*[:\-]", re.IGNORECASE)


def _strip_credits(desc: str) -> str:
    """Retire les segments d'attribution d'une description.

    La description est une suite de segments « A | B | C » (et parfois de
    lignes). On retire tout segment qui EST une mention d'attribution ; on ne
    touche à rien d'autre — un segment « Size: … » ou « Tags: … » est conservé.
    """
    lignes = []
    for ligne in (desc or "").split("\n"):
        gardes = [s for s in ligne.split("|") if not _CREDITS_SEG_RE.match(s)]
        nouvelle = " | ".join(s.strip() for s in gardes if s.strip())
        if nouvelle or not ligne.strip():
            lignes.append(nouvelle)
    return "\n".join(lignes).strip()
_SECTION_FMT = {"exfat", "backport", "dlc", "dump", "standard", "fix"}


def _base_format(file_format) -> str:
    """Type de PAQUET de base (PKG/FPKG/APR-EMU…), hors conteneurs et hors
    libellés de section (exFAT/Backport/DLC). Étiquette de la section « Standard »."""
    if not isinstance(file_format, list):
        return ""
    tags: list[str] = []
    for f in file_format:
        fl = str(f).lower()
        if fl in _CONTAINER_FMT or fl in _SECTION_FMT or fl.startswith("backport") or fl == "unknown":
            continue
        if str(f) not in tags:
            tags.append(str(f))
    # Ordre CANONIQUE, pas l'ordre d'arrivée : le même jeu de formats sortait
    # « APR-EMU · PKG » ou « PKG · APR-EMU » selon la source, ce qui affichait
    # deux libellés différents pour une réalité identique (1 078 vs 1 035 liens
    # mesurés). Le type de paquet d'abord, les qualificatifs ensuite.
    return " · ".join(sorted(tags, key=lambda t: (_BASE_FMT_ORDER.get(t.lower(), 50), t.lower())))


def _strip_unknown(fmt_str: str) -> str:
    """Retire les jetons « unknown » d'un format « a · b · unknown »."""
    parts = [p.strip() for p in (fmt_str or "").split("·")
             if p.strip() and p.strip().lower() != "unknown"]
    return " · ".join(parts)


def _link_format(name: str, url: str, game_fmt: str, base_fmt: str, group: str) -> str:
    """Format SPÉCIFIQUE d'un lien. Priorité :
      1) la SECTION captée au scraping (group : exFAT/Backport/DLC/Dump) — fiable ;
      2) heuristique nom + URL (DLC, version backport, exfat/pkg/fpkg/apr-emu) ;
      3) section « Standard » -> format de paquet de base (PKG/FPKG/APR-EMU) ;
      4) repli sur le format du jeu (hôtes à hash sans info exploitable)."""
    g = (group or "").strip()
    blob = f"{name} {url}".lower()

    def _backport_with_version() -> str:
        m = re.search(r"\b([4-9])\.xx\b", blob) or re.search(r"[-_/]([4-9])\.\d{2}[-_/]", blob)
        return f"Backport {m.group(1)}.xx" if m else "Backport"

    # 1) Section identifiée au scraping (sauf « Standard », traité plus bas)
    if g and g.lower() != "standard":
        return _backport_with_version() if g == "Backport" else g

    # 2) Heuristique nom/URL
    if "dlc" in blob:
        return "DLC"
    fmts: list[str] = []
    if "exfat" in blob:
        fmts.append("exFAT")
    if "fpkg" in blob:
        fmts.append("FPKG")
    elif re.search(r"\bpkg\b", blob):
        fmts.append("PKG")
    if re.search(r"apr[\s_-]?emu", blob):
        fmts.append("APR-EMU")
    if re.search(r"\b([4-9])\.xx\b", blob) or re.search(r"[-_/]([4-9])\.\d{2}[-_/]", blob):
        fmts.append(_backport_with_version())
    elif "backport" in blob:
        fmts.append("Backport")
    detected = " · ".join(dict.fromkeys(fmts))
    if detected:
        return detected

    # 3) Section « Standard » -> format de paquet de base
    if g.lower() == "standard" and base_fmt:
        return base_fmt
    # 4) Dernier repli. On rend le format de BASE du paquet (PKG/FPKG/APR-EMU…),
    # pas `game_fmt` : ce dernier est la CONCATÉNATION de tous les formats du
    # jeu (« exFAT · PKG · Backport »), recopiée telle quelle sur un lien dont
    # on ignore justement la nature — elle affirme trois formats là où on n'en
    # connaît aucun, et 70 % des liens du catalogue portaient cette étiquette.
    # `base_fmt` est déjà calculé et déjà passé ici : il était simplement
    # inutilisé dans ce cas.
    return base_fmt or game_fmt


_PART_RE = re.compile(r"[._\-\s]part\s*(\d{1,3})\b", re.IGNORECASE)
# Numerotation posee par un run precedent (« Viki 03/60 », « Viki #03 ») : on la
# retire avant de recalculer. Sans ca, un groupe qui s'agrandit se retrouve avec
# deux « #01 », puis « #01 #01 » au run suivant.
_RANK_SUFFIX_RE = re.compile(r"\s+(?:#\d{1,3}|\d{2,3}/\d{2,3})$")


def _number_parts(pkg: dict) -> None:
    """Suffixe « n/N » aux liens d'une archive découpée (sur place).

    Le numéro vient du nom de fichier contenu dans l'URL. Quand chaque lien du
    même libellé porte un numéro distinct, on écrit « n/N » : c'est l'ordre réel
    des parties, et un manquant se voit. Sinon (hébergeur à URL opaque), on ne
    peut rien affirmer de tel : on écrit un simple RANG « #n », qui distingue
    les liens sans prétendre à un ordre de parties ni à une totalité.
    """
    links = pkg.get("downloadLinks") or []
    groupes: dict[str, list] = {}
    for link in links:
        if isinstance(link, dict) and link.get("name"):
            groupes.setdefault(link["name"], []).append(link)
    for nom, groupe in groupes.items():
        if len(groupe) < 2:
            continue
        numeros = []
        for link in groupe:
            m = _PART_RE.search(unquote(link.get("url", "")))
            numeros.append(int(m.group(1)) if m else None)
        if any(n is None for n in numeros) or len(set(numeros)) != len(numeros):
            # Hebergeur a URL opaque (vikingfile.com/f/2hlmuAlxRy,
            # 1fichier.com/?id) : pas de nom de fichier, donc pas de numero de
            # partie a remonter. 4 877 liens sur 652 jeux portaient un libelle
            # STRICTEMENT identique a un autre du meme jeu (catalogue du
            # 2026-08-25) — l'app les affiche comme des doublons. Le rang les
            # distingue ; pas de total, faute de savoir si ce sont des parties
            # ou des miroirs.
            # ponytail: rang d'affichage, passer a « n/N » si la source finit
            # par donner le decoupage.
            for i, link in enumerate(groupe, 1):
                link["name"] = f"{nom} #{i:02d}"
            continue
        total = max(numeros)
        for link, n in zip(groupe, numeros):
            link["name"] = f"{nom} {n:02d}/{total:02d}"


def _clean_links(pkg: dict) -> int:
    """Retire les downloadLinks à URL vide/non-http ET les link-lockers (filecrypt/
    shrinkearn/clk : captcha, pas de lien direct) — sauf si ce sont les SEULS liens
    du jeu (mieux que rien). Renvoie le nb gardé."""
    links = pkg.get("downloadLinks") or []
    valid = []
    vus: set[str] = set()
    for l in links:
        url = (l.get("url") or "").strip() if isinstance(l, dict) else ""
        if not url.startswith(("http://", "https://")):
            continue
        # Entite HTML non decodee : la page source ecrit bien
        # `1fichier.com/?id&amp;af=...` dans le href (releve le 2026-08-26 sur
        # superpsx.com/dllsh2ps5/). Le chemin d'extraction qui lit le href sans
        # parseur garde l'entite, celui qui passe par BeautifulSoup la decode :
        # le MEME lien entre deux fois, et merge_links() ne peut pas le voir
        # puisqu'il dedoublonne par chaine d'URL brute. 428 liens strictement
        # identiques hors URL, sur 55 jeux (catalogue du 2026-08-25).
        url = html.unescape(url)
        if url in vus:
            continue
        vus.add(url)
        l["url"] = url
        valid.append(l)

    def _host(u: str) -> str:
        try:
            return (urlparse(u).hostname or "").lower().replace("www.", "")
        except Exception:
            return ""

    non_locker = [l for l in valid if _host(l.get("url", "")) not in _LOCKER_HOSTS]
    kept = non_locker if non_locker else valid  # lockers gardés en dernier recours
    pkg["downloadLinks"] = kept
    return len(kept)


def finalize_package(pkg: dict, stats: dict) -> None:
    # 1) sizeBytes : borne de sécurité + omission si inconnu/aberrant
    sb = pkg.get("sizeBytes")
    if sb is not None:
        if not isinstance(sb, (int, float)) or isinstance(sb, bool) or sb <= 0 or sb > MAX_SANE_BYTES:
            pkg.pop("sizeBytes", None)
            stats["size_dropped"] += 1
        else:
            pkg["sizeBytes"] = int(sb)

    # 2) fileFormat canonique
    ff = pkg.get("fileFormat")
    if ff:
        norm = normalize_formats(ff)
        if norm:
            pkg["fileFormat"] = norm

    # 3) Surfaçage du format (idempotent)
    label = display_label(pkg.get("fileFormat"))
    desc = _strip_credits(pkg.get("description") or "")
    desc_lines = [l for l in desc.split("\n") if not l.startswith("Format:")]
    desc_body = "\n".join(desc_lines).lstrip("\n")
    if label:
        pkg["formatLabel"] = label
        pkg["description"] = f"Format: {label}" + (f"\n{desc_body}" if desc_body else "")
    else:
        pkg.pop("formatLabel", None)
        pkg["description"] = desc_body

    # 3-quater) REPLI de metadonnees depuis l'extrait de la source.
    # RAWG reste prioritaire ; on ne comble QUE ce qui manque. Mesure de
    # calibration sur 135 fiches appariees : comble un genre absent 73 fois,
    # concorde avec RAWG 56 fois, diverge 6 fois (souvent plus precis cote
    # source : « Fighting » la ou RAWG dit « action »). D'ou le repli seul.
    # Interet supplementaire : ce chemin ne depend pas de la disponibilite de
    # RAWG, en panne au moment ou ceci est ecrit.
    meta = pkg.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    if pkg.get("sourceGenre") and not meta.get("genres"):
        meta["genres"] = [str(pkg["sourceGenre"]).strip()]
    if pkg.get("sourceReleased") and not meta.get("released"):
        meta["released"] = str(pkg["sourceReleased"]).strip()
    if meta:
        pkg["metadata"] = meta

    # 3bis) CARTE du jeu : l'app affiche le champ `source`. On y met le/les
    # FORMAT(s) du jeu (exFAT/PKG/Backport/APR-EMU…) — pas la vraie provenance,
    # qui reste masquée. La SOURCE PAGE (downloadSource) garde la marque.
    ff = pkg.get("fileFormat")
    fmt = pkg.get("formatLabel") or (" · ".join(ff) if isinstance(ff, list) and ff else "")
    fmt = _strip_unknown(fmt)
    pkg["source"] = [fmt] if fmt else ["PS5"]
    pkg["downloadSource"] = BRAND_SOURCE_URL

    # 3ter) On retire d'abord les liens inutilisables (URL invalide, link-lockers
    # captcha) — sauf si ce sont les seuls — puis on étiquette CHAQUE lien restant
    # avec son format (+ version) à côté de l'hébergeur. Idempotent : on retire un
    # éventuel « [..] » terminal avant de réappliquer.
    _clean_links(pkg)
    version = (pkg.get("version") or "").strip()
    base_fmt = _base_format(pkg.get("fileFormat"))
    for link in pkg.get("downloadLinks") or []:
        if not (isinstance(link, dict) and link.get("name")):
            continue
        # Idempotent : on retire l'étiquette qu'elle soit en tête (format actuel)
        # ou en fin (format historique, avant l'inversion ci-dessous).
        base = re.sub(r"^\s*\[[^\]]*\]\s*", "", link["name"])
        base = re.sub(r"\s*\[[^\]]*\]\s*$", "", base).strip()
        # Préfixe de section resté dans le nom (« Backport - Viki »). Les
        # scrapers ne l'écrivent plus, mais merge_links() ne remplace jamais un
        # `name` déjà renseigné : les liens connus des runs précédents gardaient
        # le leur indéfiniment (416 mesurés). On le retire ici, où toutes les
        # entrées repassent à chaque run — c'est le seul endroit qui répare
        # aussi l'existant.
        base = _SECTION_PREFIX_RE.sub("", base).strip() or base
        base = _RANK_SUFFIX_RE.sub("", base).strip() or base
        link_fmt = _strip_unknown(_link_format(base, link.get("url", ""), fmt, base_fmt, link.get("group", "")))
        # Version PROPRE au lien (section), sinon version du jeu en repli.
        link_version = (link.get("version") or "").strip() or version
        # ÉTIQUETTE EN TÊTE, version d'abord. L'app rend ce nom dans une boîte
        # `white-space: nowrap; text-overflow: ellipsis` d'environ 31 caractères
        # (mesuré : 180 px utiles pour 281 px requis, panneau de 319 px à 1920×1080).
        # En fin de chaîne, version et type de lien étaient TOUJOURS coupés.
        # `base` (nom du miroir) passe en dernier : il est déjà affiché juste en
        # dessous par `.download-link-host` (« 1fichier.com »), donc redondant.
        # Region du lien (EUR/USA/JPN...), lue sur le libelle de rubrique de la
        # page source par les scrapers. Presente sur 84 % des rubriques mesurees.
        # Placee EN DERNIER dans l'etiquette : version et section restent
        # prioritaires dans les ~31 caracteres visibles de l'app.
        link_region = (link.get("region") or "").strip()
        tag = " · ".join(p for p in (f"v{link_version}" if link_version else "",
                                     link_fmt, link_region) if p)
        link["name"] = f"[{tag}] {base}" if tag else base
    # Archives découpées : « …part01.rar », « …part02.rar »… produisaient N
    # libellés IDENTIQUES (12 mesurés sur Marvels Spider Man 2, PPSA03016), ce
    # qui donne l'impression de doublons alors que ce sont N fichiers dont il
    # faut la TOTALITÉ. Le numéro est dans l'URL, jamais dans le nom : on le
    # remonte, avec le total, pour qu'un manquant se voie.
    _number_parts(pkg)

    # 4) Validation Pegasus
    if not (pkg.get("titleId") or "").strip():
        stats["missing_titleId"] += 1
    if not (pkg.get("title") or "").strip():
        stats["missing_title"] += 1
    n_links = _clean_links(pkg)
    if n_links == 0:
        stats["no_valid_links"] += 1
    tid = (pkg.get("titleId") or "").strip().upper()
    if tid and not REAL_TITLEID_RE.match(tid):
        stats["placeholder_titleId"] += 1


def _cle_titre(titre: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", titre or "")
                  .encode("ascii", "ignore").decode().lower())


def _absorber_fiches_placeholder(packages: list, stats: dict) -> list:
    """Fond une fiche a identifiant fabrique dans la fiche REELLE du meme jeu.

    Un titleId `GAME_xxxxx` n'identifie rien : c'est un repli quand la page ne
    donne pas le vrai. Deux consequences mesurees le 2026-08-27 :

    - 13 groupes de titres en double contenaient une fiche a identifiant
      fabrique a cote de la vraie (« Avatar Frontiers of Pandora » GAME_23531
      contre PPSA01576) : le meme jeu, deux fois dans la liste.
    - le passage de `hash()` a sha1 change la forme de ces identifiants ; sans
      absorption, la prochaine visite de chacune de ces 15 pages creerait une
      fiche de plus a cote de l'ancienne.

    On n'absorbe QUE vers une fiche a titleId reel, et seulement s'il y en a
    EXACTEMENT une qui porte le meme titre normalise. Deux titleId reels ne
    fusionnent jamais entre eux : « Bugsnax » PPSA01502 et PPSA01503 sont deux
    editions regionales, pas un doublon — c'est une decision de catalogue, pas
    une reparation, et elle ne se prend pas ici.
    """
    reels = {}
    for pkg in packages:
        tid = (pkg.get("titleId") or "").strip().upper()
        if REAL_TITLEID_RE.match(tid):
            reels.setdefault(_cle_titre(pkg.get("title")), []).append(pkg)
    gardees, absorbees = [], 0
    for pkg in packages:
        tid = (pkg.get("titleId") or "").strip().upper()
        cible = reels.get(_cle_titre(pkg.get("title")), [])
        if REAL_TITLEID_RE.match(tid) or len(cible) != 1:
            gardees.append(pkg)
            continue
        hote = cible[0]
        vus = {l.get("url") for l in (hote.get("downloadLinks") or []) if isinstance(l, dict)}
        for link in pkg.get("downloadLinks") or []:
            if isinstance(link, dict) and link.get("url") not in vus:
                hote.setdefault("downloadLinks", []).append(link)
                vus.add(link.get("url"))
        absorbees += 1
    stats["fiches_absorbees"] = absorbees
    return gardees


def _purger_liens_etrangers(packages: list, stats: dict) -> None:
    """Retire d'une fiche les liens qui, de leur propre aveu, appartiennent a une autre.

    Un lien porte parfois `editionId` : le titleId releve sur le libelle de rubrique
    de la page source (« Version ⇛ PPSA04477 – EUR »). Quand TOUTES les occurrences
    d'une meme URL portent le meme editionId, ce lien nomme son proprietaire.

    Mesure du 2026-08-27 sur le catalogue publie : 1 450 URL sont portees par
    plusieurs titleId ; 581 d'entre elles nomment un proprietaire unique, et les 581
    sont posees sur au moins une fiche qui n'est pas lui. Deux ont ete ouvertes au
    navigateur : le nom de fichier reel confirme le proprietaire annonce
    (`[SuperPSX]-EA.Sports.UFC.5-PPSA03541-EUR-...part01.rar`, colle aussi sur
    Armored Core 6, Dying Light 2 et No Man's Sky).

    On ne retire QUE ce cas. Un lien sans editionId n'accuse personne : il reste en
    place, meme partage — la cause du recollage n'est pas tracee, et un filet qui
    devine ferait disparaitre de vrais liens.
    """
    proprio: dict[str, set] = {}
    porteurs: dict[str, list] = {}
    for pkg in packages:
        for link in pkg.get("downloadLinks") or []:
            if not isinstance(link, dict) or not link.get("url"):
                continue
            proprio.setdefault(link["url"], set()).add(link.get("editionId"))
            porteurs.setdefault(link["url"], []).append(pkg)
    vrais = {(p.get("titleId") or "").strip().upper() for p in packages}
    a_retirer = {}
    for url, eds in proprio.items():
        eds = {e for e in eds if e}
        if len(eds) != 1:
            continue
        ed = eds.pop().strip().upper()
        if not REAL_TITLEID_RE.match(ed) or ed not in vrais:
            continue  # proprietaire inconnu du catalogue : on ne touche a rien
        if any((p.get("titleId") or "").strip().upper() != ed for p in porteurs[url]):
            a_retirer[url] = ed
    if not a_retirer:
        return
    touchees = 0
    for pkg in packages:
        tid = (pkg.get("titleId") or "").strip().upper()
        avant = pkg.get("downloadLinks") or []
        apres = [l for l in avant
                 if not (isinstance(l, dict) and a_retirer.get(l.get("url")) not in (None, tid))]
        if len(apres) != len(avant):
            touchees += 1
            stats["liens_etrangers"] += len(avant) - len(apres)
            pkg["downloadLinks"] = apres
    stats["fiches_delestees"] = touchees


def finalize_catalog(catalog: dict) -> dict:
    stats = {
        "total": 0, "size_dropped": 0, "missing_titleId": 0, "missing_title": 0,
        "no_valid_links": 0, "placeholder_titleId": 0, "with_size": 0,
        "with_formatLabel": 0, "liens_etrangers": 0, "fiches_delestees": 0,
        "fiches_absorbees": 0,
    }
    # Nom du catalogue rebrandé (sinon « SuperPSX PS5 » / « exFAT PS5 » fuite
    # la source, y compris dans l'en-tête de la liste de jeux générée ensuite).
    catalog["name"] = f"{BRAND} PS5"
    packages = catalog.get("packages", [])
    stats["total"] = len(packages)
    # 1) Une fiche a identifiant fabrique est le meme jeu que la vraie : on y
    #    verse ses liens et on la retire de la liste.
    packages = _absorber_fiches_placeholder(packages, stats)
    catalog["packages"] = packages
    stats["total"] = len(packages)
    # 2) Un lien qui appartient a une autre fiche n'a rien a faire ici, et
    #    fausserait le comptage des doublons de libelle.
    _purger_liens_etrangers(packages, stats)
    for pkg in packages:
        finalize_package(pkg, stats)
        if pkg.get("sizeBytes"):
            stats["with_size"] += 1
        if pkg.get("formatLabel"):
            stats["with_formatLabel"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="Sortie (défaut: sur place)")
    ap.add_argument("--strict", action="store_true",
                    help="Sort != 0 si des jeux n'ont aucun lien valide.")
    args = ap.parse_args(argv)

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if "packages" not in catalog:
        print("Fichier invalide : clé 'packages' absente.", file=sys.stderr)
        return 1

    stats = finalize_catalog(catalog)
    out = args.out or args.catalog
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"Finalisation : {stats['total']} jeux | {stats['with_size']} avec taille | "
        f"{stats['with_formatLabel']} avec formatLabel | "
        f"{stats['size_dropped']} tailles aberrantes retirées | "
        f"{stats['no_valid_links']} sans lien valide | "
        f"{stats['placeholder_titleId']} titleId placeholder | "
        f"{stats['missing_title']} sans titre | "
        f"{stats['liens_etrangers']} liens etrangers retires "
        f"({stats['fiches_delestees']} fiches) | "
        f"{stats['fiches_absorbees']} fiches a identifiant fabrique absorbees"
    )
    if args.strict and stats["no_valid_links"] > 0:
        print("::error::Des jeux n'ont aucun lien de téléchargement valide.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
