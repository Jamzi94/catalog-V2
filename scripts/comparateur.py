# -*- coding: utf-8 -*-
"""Confronte le NOM DE FICHIER releve chez l'hebergeur a l'ETIQUETTE du catalogue.

Regle : on ne conclut QUE lorsque les deux cotes affirment quelque chose. Un nom
de fichier muet sur le format ne valide pas l'etiquette — il rend « non mesure ».
"""
import re

FORMATS = [
    ("exFAT", r"(?i)\bex[\s._-]?fat\b|\.exfat\b"),
    ("APR-EMU", r"(?i)\bapr[\s._-]?emu\b"),
    ("FPKG", r"(?i)\bfpkg\b"),
    ("DLC", r"(?i)\bdlcs?\b"),
    ("Backport", r"(?i)\bback[\s._-]?por[tk]\b"),
    ("Fix", r"(?i)\bfix\b"),
    ("PKG", r"(?i)\bpkg\b|\.pkg\b"),
]
RE_VERSION = re.compile(r"(?i)\(?v(\d{1,2}\.\d{2,3}(?:\.\d{1,3})?)\)?")
RE_REGION = re.compile(r"(?i)[-_.\s(]((?:EUR|USA|JPN|JAP|ASIA|KOR|CHN|HK))[-_.\s)]")
RE_PART = re.compile(r"(?i)\bpart[\s._-]?(\d{1,3})\b")
RE_ETIQ = re.compile(r"^\[([^\]]*)\]\s*(.*)$")


def _norm_v(v: str) -> tuple:
    """Version comparable. « 1.000 », « 01.000 » et « 01.00 » designent la meme
    version : le site ecrit sans zero de tete et tronque les zeros de fin. Les
    comparer en chaine fabriquait 5 fausses contradictions sur 79 mesures."""
    parties = [p.lstrip("0") or "0" for p in (v or "").split(".")]
    while len(parties) > 1 and parties[-1] == "0":
        parties.pop()
    return tuple(int(p) for p in parties if p.isdigit())


def _forme(v: str) -> tuple:
    """Gabarit d'ecriture d'une version : (nb de composants, largeur de chacun).

    Le MAJOR est exclu : son zero de tete est du remplissage, pas une
    convention — « 1.005 » et « 01.031 » s'ecrivent pareil et se comparent.
    Ce qui suit, en revanche, distingue des conventions incompatibles :

        « 01.10 » (2,)      contre « 1.100 » (3,)        mineur tronque
        « 01.000.008 » (3,3) contre « 1.008 » (3,)       build promu en mineur
        « 1.07 » (2,)       contre « 1.007.004 » (3,3)   build omis

    Deux versions de formes differentes ne se comparent pas : c'est la qu'on ne
    SAIT pas, et se taire vaut mieux qu'accuser au hasard.
    """
    return tuple(len(p) for p in (v or "").split(".")[1:])


def lire_nom(nom: str) -> dict:
    """Ce que le NOM DE FICHIER affirme. Champ absent = il ne dit rien."""
    f = {}
    fmts = [n for n, p in FORMATS if re.search(p, nom or "")]
    if fmts:
        f["formats"] = fmts
    m = RE_VERSION.search(nom or "")
    if m:
        f["version"] = m.group(1)
    m = RE_REGION.search(nom or "")
    if m:
        f["region"] = m.group(1).upper().replace("JAP", "JPN")
    m = RE_PART.search(nom or "")
    if m:
        f["part"] = int(m.group(1))
    return f


def lire_etiquette(nom: str) -> dict:
    """Ce que l'ETIQUETTE affirme."""
    e = {}
    m = RE_ETIQ.match(nom or "")
    if not m:
        return e
    tete, reste = m.group(1), m.group(2)
    morceaux = [p.strip() for p in tete.split("·")]
    for p in morceaux:
        if re.fullmatch(r"(?i)v\d.*", p):
            e["version"] = p[1:]
        elif re.fullmatch(r"(?i)EUR|USA|JPN|ASIA|KOR|CHN|HK", p):
            e["region"] = p.upper()
        elif p:
            # L'etiquette abrege « Backport » en « BP » (pegasus_finalize).
            # Sans cette relecture, toute etiquette BP passerait pour une
            # « mention Backport absente » : un trou creuse par notre propre
            # abreviation.
            e.setdefault("formats", []).append(
                ("Backport" + p[2:]) if p.upper() == "BP"
                or p.upper().startswith("BP ") else p)
    m = re.search(r"#(\d+)$", reste.strip())
    if m:
        e["rang"] = int(m.group(1))
    m = re.search(r"(\d+)/(\d+)$", reste.strip())
    if m:
        e["n_sur_N"] = int(m.group(1))
    return e


def comparer(nom_fichier: str, etiquette: str, group: str = "") -> list:
    """Liste des contradictions AVEREES. Vide = rien a redire (pas « tout bon »).

    `group` est la section posee au scraping. Elle sert a NE PAS reprocher une
    mention deductible : « Backport N.xx » implique exFAT — sur 732 liens de
    cette section dont le nom de fichier a ete releve le 2026-08-30, 621 disent
    exFAT et AUCUN ne dit PKG. Sans cette regle, 618 ecarts sont de la
    sur-detection, aussi fausse qu'un zero rassurant.

    La regle n'est pas un baillon : un fichier qui dit PKG sous une telle
    section reste une contradiction, et le test le verifie.
    """
    f, e = lire_nom(nom_fichier), lire_etiquette(etiquette)
    ecarts = []
    # « Backport 4.xx » ET « Backport » nu impliquent l'un comme l'autre
    # exFAT — 621 releves sur 621, aucun PKG. N'accepter que la forme avec
    # numero faisait reclamer « mention exFAT absente » sur des etiquettes
    # ou pegasus_finalize s'abstient volontairement de l'ecrire.
    implique_exfat = bool(re.match(r"(?i)back[\s._-]?por[tk]", (group or "").strip()))
    if "formats" in f and "formats" in e:
        # exFAT et PKG se contredisent ; Backport/DLC/Fix se cumulent avec un
        # format de paquet, donc on ne compare que la famille « contenant ».
        contenant = {"exFAT", "PKG", "FPKG"}
        fc = {x for x in f["formats"] if x in contenant}
        ec = {x for x in e["formats"] if x in contenant}
        if fc and ec and not (fc & ec):
            ecarts.append(f"format: fichier dit {sorted(fc)}, etiquette dit {sorted(ec)}")
        # une mention forte du nom absente de l'etiquette
        for marqueur in ("DLC", "Backport", "exFAT"):
            if marqueur == "exFAT" and implique_exfat:
                continue
            # Appartenance par SOUS-CHAINE : l'etiquette porte « Backport 4.xx »
            # la ou le nom de fichier dit « Backport ». Une egalite stricte
            # comptait la mention absente alors qu'elle est bien la — precision
            # de la variante, pas absence du marqueur.
            if (marqueur in f["formats"]
                    and not any(marqueur in x for x in e["formats"])
                    and marqueur not in ec):
                ecarts.append(f"mention absente de l'etiquette : {marqueur}")
    if implique_exfat and "formats" in f:
        # La section implique exFAT : un fichier qui annonce PKG n'est pas une
        # mention manquante, c'est une contradiction. C'est le temoin qui prouve
        # que la regle « Backport N.xx implique exFAT » n'est pas un baillon.
        if "PKG" in f["formats"] and "exFAT" not in f["formats"]:
            ecarts.append("format: section implique exFAT, fichier dit PKG")
    if "version" in f and "version" in e:
        # DEUX VERSIONS NE SE COMPARENT QUE SI ELLES ONT LA MEME FORME. Les
        # sources ecrivent la MEME version PS5 de trois façons incompatibles :
        # trois conventions incompatibles pour la MEME version PS5 :
        #   « v01.10 » et « 1.100 »        (mineur tronque de ses zeros)
        #   « v01.000.008 » et « 1.008 »   (build promu en mineur)
        #   « v1.07 » et « 1.007.004 »     (build omis)
        # Mesure du 2026-09-01 sur les 60 ecarts de version restants : 3 ont un
        # MAJOR different — de vraies contradictions — et 57 ne different que
        # par la notation. Comparer au-dela du major, c'est produire 95 % de
        # faux positifs, et la sur-detection vaut le faux zero.
        # Mesure du 2026-09-01 sur les 60 ecarts restants : 57 opposent des
        # formes DIFFERENTES et ne sont que des notations ; 3 seulement ont un
        # major different. Mais ignorer tout sauf le major serait l'exces
        # inverse — « 01.005 » et « 01.031 » ont le meme major et sont bien
        # deux versions distinctes. On compare donc a forme egale, et on se
        # tait quand les formes different : c'est la ou l'on ne SAIT pas.
        vf, ve = _norm_v(f["version"]), _norm_v(e["version"])
        meme_forme = _forme(f["version"]) == _forme(e["version"])
        if vf and ve and ((meme_forme and vf != ve) or vf[0] != ve[0]):
            ecarts.append(f"version: fichier {f['version']}, etiquette {e['version']}")
    if "region" in f and "region" in e and f["region"] != e["region"]:
        ecarts.append(f"region: fichier {f['region']}, etiquette {e['region']}")
    # Le rang « #n » n'affirme RIEN : _number_parts l'ecrit comme un ordre
    # d'affichage et refuse explicitement de pretendre a un ordre de parties
    # (il n'ecrit « n/N » que lorsque l'URL porte le numero). Lui reprocher de
    # ne pas coller au partNN du fichier, c'est accuser l'etiquette d'une
    # affirmation que le code se garde de faire — 289 faux ecarts.
    if "part" in f and "n_sur_N" in e and f["part"] != e["n_sur_N"]:
        ecarts.append(f"rang: fichier part{f['part']:02d}, etiquette {e['n_sur_N']:02d}/N")
    return ecarts


def mesurable(nom_fichier: str, etiquette: str) -> bool:
    f, e = lire_nom(nom_fichier), lire_etiquette(etiquette)
    return bool((set(f) & set(e)) or ("part" in f and "n_sur_N" in e))
