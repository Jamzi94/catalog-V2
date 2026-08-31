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

# URL qui ne menent a AUCUN fichier, meme si l'hote en heberge par ailleurs :
# un encart d'affiliation vers l'offre premium et une image de promotion.
# Mesure du 2026-08-27 : 52 liens rapidgator dans le catalogue, 43 en
# /article/premium/ref (le MEME encart sur 43 fiches) et 9 en /images/pics —
# aucun en /file. Aucune fiche n'a que ceux-la, donc aucune ne se vide.
_CHEMINS_SANS_FICHIER = ("rapidgator.net/article/", "rapidgator.net/images/")

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


# Notation de firmware SANS point : les pages et les noms de fichiers ecrivent
# « 4XX PPSA10965 – USA » la ou le detecteur ne cherchait que la forme pointee.
# 361 liens portent cette notation, 261 sans « Backport » dans l etiquette : un
# backport annonce PKG. Les bornes non-alphanumeriques evitent d attraper un
# hash d hebergeur — « abc4xxdef », « PPSA4XX999 » et « noxnx2hel81dr92 » ne
# matchent pas (temoins executes dans test_pegasus_finalize).
_RE_FW_SANS_POINT = re.compile("(?<![a-z0-9])([4-9])xx(?![a-z0-9])")

_LEGENDE_BP = "BP = Backport"

# Un lien « BP » est tantot le JEU entier repackage, tantot le seul binaire a
# deposer dans le dossier du jeu. Mesure du 2026-08-30 sur 114 tailles relevees
# chez les hebergeurs, tirees au sort parmi les liens BP : la distribution est
# BIMODALE — mais SEULEMENT dans la section « Backport » sans numero. Reprise
# sur 858 tailles mesurees (et non plus 114) :
#   « Backport N.xx » (n=398) : mediane 22,8 Go, ZERO correctif sous 100 Mo, et
#       la densite au « creux » vaut 88,6 % du pic — il n'y a pas de vallee, ce
#       sont tous des jeux. Ma premiere lecture, sur 114 points, etait fausse.
#   « Backport » seul (n=214) : vallee REELLE, densite au creux 3,5 % du pic.
# Le seuil est derive, pas choisi : les deux observations qui encadrent le creux
# sont 217 Mo et 893 Mo — un saut x4,1 sans une seule mesure entre les deux, et
# tout seuil dans cet intervalle donne le MEME classement (119 correctifs,
# 95 jeux). 440 Mo en est le milieu geometrique. Le test tient l'intervalle.
SEUIL_CORRECTIF = 440 * 1024 ** 2


# Marques du NOM DE FICHIER releve chez l'hebergeur. Validees le 2026-08-30 sur
# 1206 liens ayant a la fois un nom releve et une taille mesuree : le
# classifieur tranche 978 d'entre eux (81 %) et se trompe 8 fois — 99 %
# d'exactitude sur ce qu'il tranche, contre un seuil de taille qui ne couvre que
# 1123 liens et depend d'une vallee statistique.
#   « backport » 163/163 correctifs · « .zip » 132/132 · « @bestpig » 22/22 ·
#   « 4.xx » 115/117 · « .exfat » 5/429 (99 % de jeux) · « partNN » 0/13.
_MARQUES_JEU = (".exfat",)
_MARQUES_CORRECTIF = ("backport", "@bestpig", ".zip")


def marques_du_nom(nom) -> set:
    """Ce que le NOM DE FICHIER affirme du contenu : {DLC, exFAT, Backport, Fix}.

    Mesure du 2026-08-30 sur 8575 noms releves chez les hebergeurs : le nom dit
    « DLC » 653 fois, l'etiquette 438 — 341 liens dont la source avait perdu
    l'information. Un cas verifie : 124 liens sont passes de group=DLC a
    Standard/exFAT au re-scrape, et 41 des 43 dont on connait le nom disent
    « DLC » dans le fichier lui-meme.

    Ces marques AJOUTENT a l'etiquette, elles n'en retirent jamais : l'etiquette
    dit DLC 126 fois la ou le nom se tait, et c'est la source qui le sait.

    Les mots sont cherches comme des MOTS. « abcdlcdef » n'est pas un DLC, et le
    test le tient — sans quoi on etiquetterait au hasard des identifiants
    d'hebergeur.
    """
    b = (nom or "").lower()
    if not b:
        return set()
    trouve = set()
    if re.search("(^|[^a-z])dlcs?([^a-z]|$)", b):
        trouve.add("DLC")
    if ".exfat" in b or re.search("(^|[^a-z])exfat([^a-z]|$)", b):
        trouve.add("exFAT")
    if ("backport" in b or "@bestpig" in b
            or any(f"{n}.xx" in b for n in "456789")
            or any(f"{n}xx" in b for n in "456789")):
        trouve.add("Backport")
    if re.search("(^|[^a-z])fix([^a-z]|$)", b):
        trouve.add("Fix")
    return trouve


def format_du_nom(nom):
    """Le format de CONTENANT que le nom de fichier AFFIRME : exFAT, FPKG, PKG.

    Rend None quand il ne dit rien — on ne devine pas. C'est la difference avec
    marques_du_nom, qui rend des mentions cumulables (DLC, Fix) ; ici les trois
    valeurs s'excluent : un fichier est une image exFAT OU un paquet.

    Pourquoi lire au lieu de deduire. « Backport implique exFAT » etait vrai a
    621 releves sur 621, puis a 1359 sur 1359 — mais la mesure du 2026-08-30 sur
    les 3020 liens de section Backport trouve 1626 noms qui disent exFAT et UN
    qui dit FPKG. Un seul contre-exemple suffit : un backport est compatible
    exFAT comme FPKG, le format se lit, il ne se postule pas.

    FPKG est teste AVANT PKG : le mot contient l'autre, et l'ordre inverse
    ferait passer tous les FPKG pour des PKG.
    """
    b = (nom or "").lower()
    if not b:
        return None
    if ".exfat" in b or re.search("(^|[^a-z])exfat([^a-z]|$)", b):
        return "exFAT"
    if re.search("(^|[^a-z])fpkg([^a-z]|$)|[.]fpkg", b):
        return "FPKG"
    if re.search("(^|[^a-z])pkg([^a-z]|$)|[.]pkg", b):
        return "PKG"
    return None



_REGIONS = ("EUR", "USA", "JPN", "JAP", "ASIA", "KOR", "CHN", "HK")


_RE_TID_NOM = re.compile("(?i)(PPSA|CUSA)[0-9]{4,}")


def _titleid_du_nom(nom):
    """titleId Sony lu dans le nom de fichier, ou None. Sert a verifier qu'un
    fichier appartient bien a la fiche avant de lui emprunter quoi que ce soit."""
    m = _RE_TID_NOM.search(nom or "")
    return m.group(0).upper() if m else None


_RE_VERSION_NOM = re.compile("(?i)[(]?v([0-9]{1,2}[.][0-9]{2,3}(?:[.][0-9]{1,3})?)[)]?")


def _version_du_nom(nom):
    """Version lue dans le nom de fichier, ou None. « (v01.005.400) », « v1.02 »."""
    m = _RE_VERSION_NOM.search(nom or "")
    return m.group(1) if m else None


def region_du_nom(nom):
    """Region lue dans le nom de fichier, ou None.

    Mesure du 2026-08-30 : sur 257 liens portant une region des DEUX cotes,
    254 s'accordent — 99 %. Et 2788 liens la portent dans le NOM sans l'avoir
    dans le champ releve au scraping : l'information etait la, personne ne la
    lisait.

    Le champ de la source PRIME quand les deux parlent : les 3 desaccords
    mesures ne tranchent pas en faveur du nom, ils signalent plutot un lien
    recolle sur la mauvaise fiche (« -USA- » dans le fichier, EUR a l'etiquette).

    Bornes strictes : trois majuscules ne font pas une region. « PKG », « RAR »,
    « MOUSA » ne doivent rien declencher — le test le tient.
    """
    if not nom:
        return None
    m = re.search("(?:^|[-_. (])(" + "|".join(_REGIONS) + ")(?:[-_. )]|$)", nom, re.I)
    if not m:
        return None
    return m.group(1).upper().replace("JAP", "JPN")


def numero_de_partie(nom):
    """Numero de partie VRAI, lu dans le nom de fichier, ou None.

    Le rang « #n » que pose _number_parts n'est qu'un ordre d'affichage : sur
    354 liens multipart qui en portaient un, il ne valait le vrai numero que
    45 fois — 12 %. Le nom de fichier, lui, le donne.
    """
    m = re.search("(^|[^a-z])part[ ._-]*0*([0-9]{1,3})([^0-9]|$)", (nom or "").lower())
    return int(m.group(2)) if m else None


def classer_par_nom(nom) -> str:
    """« jeu », « correctif » ou « inconnu », d'apres le seul nom de fichier.

    Les marques de JEU l'emportent : un nom qui porte les deux (« Backport ...
    part03.rar », « PPSA31246-backport.exfat ») designe un jeu decoupe ou une
    image exFAT, pas le binaire a deposer dans le dossier. C'est la lecture des
    contre-exemples, pas une preference.

    On rend « inconnu » plutot que de basculer vers la classe majoritaire : un
    classifieur qui repond toujours ne se trompe jamais a moitie, il se trompe
    silencieusement.
    """
    b = (nom or "").strip().lower()
    if not b:
        return "inconnu"
    if any(m in b for m in _MARQUES_JEU) or re.search("part[ ._-]*[0-9]", b):
        return "jeu"
    if (any(m in b for m in _MARQUES_CORRECTIF)
            or any(f"{n}.xx" in b for n in "456789")):
        return "correctif"
    return "inconnu"


def _taille_courte(octets) -> str:
    """« 45 Mo », « 1 Go », « 101 Go » — un entier, jamais de virgule.

    Pas de decimale, demande du 2026-08-30. On lit cette taille pour trancher
    « correctif ou jeu », pas pour connaitre l'octet pres : « 1.1 Go » et
    « 1 Go » repondent la meme chose et le point coute deux caracteres dans une
    etiquette qui en manque. Sous le Go on reste en Mo, ou l'entier porte deja
    trois chiffres utiles.
    """
    if not octets or not isinstance(octets, (int, float)) or octets <= 0:
        return ""
    Mo = 1024 ** 2
    if octets < 1024 ** 3:
        return f"{round(octets / Mo)} Mo"
    return f"{round(octets / 1024 ** 3)} Go"


def _grappe(link: dict) -> tuple:
    """Rubrique d'un lien : meme section, meme version, meme edition.

    Les liens d'une meme rubrique sont le MEME fichier chez plusieurs
    hebergeurs — « Backport 4.xx+ ⇛ Viki – Rootz – OneFile » sur la page source.
    Une seule sonde de taille vaut donc pour toute la rubrique.
    """
    return (link.get("group"), link.get("version"),
            link.get("region"), link.get("editionId"))


def _propager_tailles(pkg: dict) -> None:
    """NE PROPAGE PLUS RIEN — elle NETTOIE les tailles heritees d'avant.

    Cette fonction etendait la taille mesuree aux miroirs de la meme rubrique,
    sur l'hypothese « une rubrique = un fichier ». Elle portait la couverture de
    32 % a 87 % des etiquettes BP. Le temoin l'a tuee : en sondant un SECOND
    miroir de 61 rubriques deja mesurees, 53 rendent une taille DIFFERENTE et
    15 changent de classement jeu/correctif. Un cas mesure : sur « Lollipop
    Chainsaw RePoP », un lien Mediafire que la sonde donne a 43 Mo avait herite
    de 39,7 Go.

    La cause est que `group` ne capture pas l'identite de la rubrique source :
    il vaut souvent None ou « Standard » pour des lignes differentes, et une
    meme grappe melangeait dix liens dont un correctif et le jeu. Tant que le
    libelle brut de la rubrique n'est pas stocke (le `srcLabel` du plan), il n'y
    a aucune cle fiable pour regrouper des miroirs.

    On n'affiche donc que ce qui a ete MESURE sur CE lien. Une taille fausse est
    pire qu'une taille absente : elle se lit comme une preuve.
    """
    for l in (pkg.get("downloadLinks") or []):
        if isinstance(l, dict) and l.pop("_tailleHeritee", None):
            l.pop("sizeBytes", None)


def _noyau(v: str) -> str:
    """Version reduite au minimum : zero de tete et segments de queue nuls otes."""
    p = [x for x in (v or "").split(".")]
    while len(p) > 2 and p[-1].strip("0") == "":
        p.pop()
    if p and p[0][:1] == "0" and p[0].strip("0") != "":
        p[0] = p[0].lstrip("0")
    return ".".join(p)


def abreger_versions(versions) -> dict:
    """Forme la plus courte NON AMBIGUE de chaque version, fiche par fiche.

    « 01.200.000 » seul sur sa fiche devient « 1.200 » : les zeros de queue et
    le zero de tete ne portent aucune information. Mais s'il cohabite avec
    « 01.200.007 », la forme courte serait le PREFIXE de l'autre — un lecteur ne
    saurait plus laquelle il lit. On remonte alors d'un cran, jusqu'a une forme
    qui ne prefixe aucune autre version de la fiche et qu'aucune ne prefixe.

    C'est pourquoi l'abreviation est calculee par fiche et non une fois pour
    toutes : elle depend des versions qui se cotoient a l'ecran.
    """
    versions = {v for v in versions if v is not None}
    out: dict = {}
    for v in versions:
        autres = versions - {v}
        interdits = {a for a in autres} | {_noyau(a) for a in autres}
        p = v.split(".")
        sans_queue = list(p)
        while len(sans_queue) > 2 and sans_queue[-1].strip("0") == "":
            sans_queue.pop()
        def _sans_tete(bouts):
            b = list(bouts)
            if b and b[0][:1] == "0" and b[0].strip("0") != "":
                b[0] = b[0].lstrip("0")
            return ".".join(b)
        candidats = [_sans_tete(sans_queue), ".".join(sans_queue), _sans_tete(p), v]
        vus = []
        for c in candidats:
            if c not in vus:
                vus.append(c)
        choisi = v
        for c in sorted(vus, key=len):
            if any(c and (c.startswith(a) or a.startswith(c)) for a in interdits if a):
                continue
            choisi = c
            break
        out[v] = choisi
    return out



def _abreger(fmt: str) -> str:
    """« Backport » -> « BP » dans l'ETIQUETTE seulement.

    Le champ `group` garde le mot entier : c'est de la donnee, pas de
    l'affichage, et les scrapers comme les tests s'appuient dessus. L'etiquette,
    elle, est rendue dans une boite de 180 px avec ellipse, ou « Backport 4.xx »
    pese six caracteres de trop. La legende « BP = Backport » est ajoutee a la
    description de la fiche pour que l'abreviation ne soit pas un rebus.

    Remplacement litteral : les seules formes produites en amont sont
    « Backport » et « Backport N.xx » (detect_group dans formats.py et
    _backport_with_version ci-dessous), toutes deux capitalisees ainsi.
    """
    return (fmt or "").replace("Backport", "BP")


def _link_format(name: str, url: str, game_fmt: str, base_fmt: str, group: str) -> str:
    """Format SPÉCIFIQUE d'un lien. Priorité :
      1) la SECTION captée au scraping (group : exFAT/Backport/DLC/Dump) — fiable ;
      2) heuristique nom + URL (DLC, version backport, exfat/pkg/fpkg/apr-emu) ;
      3) section « Standard » -> format de paquet de base (PKG/FPKG/APR-EMU) ;
      4) repli sur le format du jeu (hôtes à hash sans info exploitable)."""
    g = (group or "").strip()
    blob = f"{name} {url}".lower()

    def _backport_with_version() -> str:
        m = (re.search(r"\b([4-9])\.xx\b", blob) or re.search(r"[-_/]([4-9])\.\d{2}[-_/]", blob)
             or _RE_FW_SANS_POINT.search(blob))
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
    if (re.search(r"\b([4-9])\.xx\b", blob) or re.search(r"[-_/]([4-9])\.\d{2}[-_/]", blob)
            or _RE_FW_SANS_POINT.search(blob)):
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
    groupes: dict[tuple, list] = {}
    for link in links:
        if isinstance(link, dict) and link.get("name"):
            # Par (etiquette, HOTE) : depuis que le miroir a quitte l'etiquette,
            # grouper par le seul libelle melangerait des miroirs — or deux
            # miroirs ne sont pas deux parties, et l'hote affiche dessous les
            # distingue deja. On ne numerote donc que les doublons d'un meme
            # hebergeur, les seuls que l'utilisateur ne peut pas departager.
            try:
                hote = urlparse(link.get("url", "")).hostname or ""
            except Exception:                                # noqa: BLE001
                hote = ""
            groupes.setdefault((link["name"], hote.replace("www.", "")), []).append(link)
    for (nom, _hote), groupe in groupes.items():
        if len(groupe) < 2:
            continue
        numeros = []
        for link in groupe:
            # Le NOM DE FICHIER d'abord : il porte le VRAI numero. Le rang
            # d'affichage « #n » ne valait le vrai numero que 45 fois sur 354
            # liens multipart mesures (12 %) — il ordonnait par position dans le
            # catalogue, pas par partie.
            n = numero_de_partie(link.get("fileName"))
            if n is None:
                m = _PART_RE.search(unquote(link.get("url", "")))
                n = int(m.group(1)) if m else None
            numeros.append(n)
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


def _cle_url(url: str) -> str:
    """Cle de dedoublonnage : la MEME ressource sous deux ecritures.

    On ne dedoublonnait que sur la chaine brute apres html.unescape, donc ni le
    « www. » ni le pourcent-encodage n'etaient normalises. Mesure du
    2026-08-30 : 458 liens en double dans une meme fiche, sur 121 jeux, dont 229
    portant DEUX etiquettes differentes — au moins une des deux est fausse, et
    _number_parts les numerote comme s'il fallait telecharger les deux.

    On normalise l'hote (minuscule, sans « www. ») et on dechiffre le
    pourcent-encodage du chemin et de la requete. On ne touche NI au chemin
    lui-meme NI a l'ordre des parametres : deux ressources differentes doivent
    rester deux liens, et le test le verifie.
    """
    try:
        u = urlparse(url)
    except Exception:                                        # noqa: BLE001
        return url
    hote = (u.hostname or "").lower()
    if hote.startswith("www."):
        hote = hote[4:]
    chemin = unquote(u.path or "").replace("+", " ")
    requete = unquote(u.query or "").replace("+", " ")
    return f"{hote}{chemin}?{requete}" if requete else f"{hote}{chemin}"


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
        if any(motif in url for motif in _CHEMINS_SANS_FICHIER):
            continue
        cle = _cle_url(url)
        if cle in vus:
            continue
        vus.add(cle)
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
    desc_lines = [l for l in desc.split("\n") if not l.startswith("Format:") and l.strip() != _LEGENDE_BP]
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
    # AVANT l'etiquetage : une taille heritee d'un miroir de la meme rubrique
    # doit pouvoir atteindre l'etiquette. Posee apres, elle arrivait trop tard —
    # le test d'integration l'a montre.
    _propager_tailles(pkg)
    version = (pkg.get("version") or "").strip()
    base_fmt = _base_format(pkg.get("fileFormat"))
    # Abreviation des versions, calculee POUR CETTE FICHE : elle depend des
    # versions qui se cotoient a l'ecran. La version de la fiche entre dans le
    # calcul sans etre affichee — une forme courte ne doit pas non plus se
    # confondre avec celle de l'en-tete.
    _abrege = abreger_versions(
        {(l.get("version") or "").strip() for l in pkg.get("downloadLinks") or []
         if isinstance(l, dict)} | {version})
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
        # Le nom du miroir sort de l'AFFICHAGE mais reste dans la DONNEE : il
        # sert encore aux heuristiques de format (_link_format lit nom + URL) et
        # une etiquette n'est pas un endroit ou ranger de l'information.
        if base and not base.startswith("["):
            link.setdefault("mirror", base)
        base = link.get("mirror") or base
        link_fmt = _strip_unknown(_link_format(base, link.get("url", ""), fmt, base_fmt, link.get("group", "")))
        # Version PROPRE au lien (section), sinon version du jeu en repli.
        link_version = (link.get("version") or "").strip() or version
        # Le NOM DE FICHIER arbitre quand il CONFIRME la fiche. Mesure du
        # 2026-08-30 sur les 110 contradictions de version : 24 sont de cette
        # forme — nom == fiche, seul le champ du LIEN diverge, deux sources
        # independantes contre une. La version cesse alors d'etre ecrite,
        # puisqu'elle egale celle de la fiche, affichee juste au-dessus.
        # Les 88 autres, ou le nom differe des DEUX, restent ouvertes : rien
        # dans le catalogue ne permet de trancher, et inventer serait pire.
        _v_nom = _version_du_nom(link.get("fileName"))
        if _v_nom and version and _noyau(_v_nom) == _noyau(version):
            link_version = version
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
        _tid = (pkg.get("titleId") or "").strip().upper()
        _region_nom = region_du_nom(link.get("fileName"))
        if (_region_nom and link_region and _region_nom != link_region
                and _titleid_du_nom(link.get("fileName")) == _tid):
            # Les deux parlent et se contredisent — 9 cas mesures le 2026-08-30.
            # Le nom ne l'emporte QUE s'il porte le titleId de cette fiche.
            # Sans cette condition la regle etait fausse, et un test l'a
            # attrapee : sur les 9, QUATRE portent le titleId d'un AUTRE jeu
            # (« Atomic Heart PPSA10695 » sur la fiche PPSA15493, « Resident
            # Evil 4 PPSA07412 » sur PPSA07411). Ce sont des liens recolles, et
            # adopter leur region afficherait celle du mauvais jeu — le test
            # test_marques_nom disait exactement cela, il avait raison.
            # Restent les 4 ou le nom porte BIEN le titleId de la fiche
            # (« Biomutant PPSA06255 …EUR.rar » etiquete USA) : la, le fichier
            # est le bon et c'est lui qui decrit ce qu'on telecharge.
            link_region = _region_nom
        if not link_region:
            # Le champ est vide : le nom de fichier comble. 2788 liens sont dans
            # ce cas. On ne remplace JAMAIS un champ renseigne — voir
            # region_du_nom pour la mesure d'accord.
            link_region = region_du_nom(link.get("fileName")) or ""
        # La version n'est ecrite QUE si elle differe de celle de la fiche : la
        # vue detail affiche deja « Version 01.031 » en en-tete, juste au-dessus
        # de la liste. Mesure du 2026-08-27 dans l'app (boite de 180 px, police
        # Manrope 650 13px, mesure canvas validee a 0,48 px pres contre le DOM) :
        # sur 100 jeux et 1729 liens, 67 % des libelles etaient coupes par
        # l'ellipse, faisant disparaitre le rang de partie (602 cas) et la region
        # (134). La version etait repetee sur 1214 d'entre eux. En la retirant
        # quand elle est redondante : 26 %. Elle reste ecrite quand elle differe,
        # c'est-a-dire exactement quand elle distingue deux liens.
        version_utile = _abrege.get(link_version, link_version) if link_version != version else ""
        # ORDRE : format, puis region, puis version. L'ellipse mange la FIN, et
        # la version est ce dont on peut le plus se passer — decision de
        # l'utilisateur, le 2026-08-30. Le reordonnancement ne change pas le
        # nombre d'etiquettes coupees (2964 sur 15955, la largeur est la meme),
        # il change ce qu'elles emportent : sur le catalogue entier, le format
        # disparaissait 290 fois et la region 369 fois ; en mettant la version
        # en dernier, 67 et 104. La version, elle, sort du cadre 465 fois — et
        # elle n'est ecrite que lorsqu'elle DIFFERE de celle de la fiche, que
        # l'en-tete affiche juste au-dessus.
        link_fmt = _abreger(link_fmt)
        # Le NOM DE FICHIER complete ce que la source a perdu. Mesure du
        # 2026-08-30 : le nom dit « DLC » 653 fois, l'etiquette 438 — et 124
        # liens sont passes de group=DLC a Standard au re-scrape, alors que
        # 41 des 43 dont on connait le nom disent DLC dans le fichier. Le nom
        # AJOUTE, il ne retire jamais : l'etiquette dit DLC 126 fois la ou le
        # nom se tait, et c'est la source qui le sait.
        # Backport et exFAT ont longtemps ete ecartes ici, sur cet argument :
        # « le premier est implique par BP N.xx (621 releves sur 621), le
        # second vient deja de la section, mieux renseignee (2407 contre
        # 1313) ». L'argument compare des VOLUMES et ne dit rien du cas ou la
        # section SE TAIT et le nom PARLE. Confrontation du 2026-08-30 des
        # 6507 liens comparables a leur nom de fichier : 551 contradictions
        # « mention Backport absente » et 101 « le fichier dit exFAT, 
        # l'etiquette dit PKG » — 652 des 664 ecarts mesures. Exemples :
        #   « …Ghost of Tsushima V02.024 Backport 4.XX By BA » -> [PKG · v2.024]
        #   « PPSA08135.exfat »                                -> [PKG]
        taille = link.get("sizeBytes")
        classe = classer_par_nom(link.get("fileName"))
        if classe == "inconnu" and isinstance(taille, (int, float)) and taille > 0:
            classe = "correctif" if taille < SEUIL_CORRECTIF else "jeu"
        _marques = marques_du_nom(link.get("fileName"))
        for _marque in ("DLC", "Fix"):
            if _marque in _marques and _marque not in link_fmt:
                link_fmt = f"{link_fmt} · {_marque}" if link_fmt else _marque
        # L'etiquette abrege Backport en BP : chercher les DEUX formes, sinon
        # on recolle la mention sur une etiquette qui la porte deja.
        if "Backport" in _marques and "BP" not in link_fmt and "Backport" not in link_fmt:
            link_fmt = f"{link_fmt} · BP" if link_fmt else "BP"
        # exFAT n'est pas une mention a AJOUTER a cote de PKG : les deux se
        # contredisent. Le nom de fichier tranche — il porte l'extension reelle
        # du contenu, la section porte le classement de la page.
        # LE FORMAT SE LIT, IL NE SE DEDUIT PAS. « Backport implique exFAT »
        # tenait a 1359 releves sur 1359 — puis un backport FPKG est apparu. Un
        # seul contre-exemple suffit : BP est compatible exFAT comme FPKG, donc
        # on ecrit le format quand le NOM DE FICHIER l'affirme, et rien sinon.
        _fmt_verifie = format_du_nom(link.get("fileName"))
        if _fmt_verifie and _fmt_verifie not in link_fmt:
            _contenant = ("FPKG" if "FPKG" in link_fmt
                          else "PKG" if "PKG" in link_fmt
                          else "exFAT" if "exFAT" in link_fmt else "")
            if _contenant:
                # L'etiquette annonce un AUTRE contenant : les deux se
                # contredisent, et c'est le nom qui tranche — il porte
                # l'extension reelle quand la section porte le classement.
                link_fmt = link_fmt.replace(_contenant, _fmt_verifie)
            elif "BP" in link_fmt or "Backport" in link_fmt:
                # Sous BP, le format ne s'ecrit que sur le JEU. En dessous du
                # seuil c'est le binaire a deposer dans le dossier : son
                # etiquette porte deja sa taille, qui en dit plus long. Mesure
                # du 2026-08-30 : 1563 BP au-dessus du seuil, 217 en dessous.
                if classe != "correctif":
                    link_fmt = f"{link_fmt} · {_fmt_verifie}"
            else:
                link_fmt = f"{link_fmt} · {_fmt_verifie}" if link_fmt else _fmt_verifie
        # Un BP sous le seuil est le BINAIRE a deposer dans le dossier du jeu,
        # pas le jeu : on affiche sa taille, qui le dit sans legende. Au-dessus,
        # c'est le jeu — la fiche porte deja sa taille et les pixels sont
        # comptes (boite de 180 px). Voir SEUIL_CORRECTIF pour la mesure.
        # Jeu ou correctif ? Le NOM DE FICHIER releve chez l'hebergeur tranche
        # 81 % des cas a 99 % d'exactitude (1206 liens de controle) ; la taille
        # ne tranche que 60 % et depend d'un seuil statistique. Le nom prime
        # donc, et la taille ne sert qu'a departager ce qu'il laisse « inconnu ».
        # LA TAILLE S'AFFICHE DES QU'ELLE EST CONNUE — demande du 2026-08-30.
        # Elle ne l'etait que sur les backports classes correctif : 1057
        # etiquettes pour 5123 liens dont la taille est connue. Cout mesure de
        # la generalisation : la troncature passe de 8,2 % a 10,7 % au-dela des
        # ~31 caracteres visibles. Elle est posee AVEC le format, donc avant la
        # region et la version — c'est la version qui sort du cadre en premier,
        # et c'est ce dont on peut le plus se passer, l'en-tete l'affichant.
        if (court := _taille_courte(taille)) and classe == "correctif"                 and ("BP" in link_fmt or "Backport" in link_fmt) and "exFAT" in link_fmt:
            # Un BP sous le seuil est le binaire a deposer dans le dossier du
            # jeu. Sa taille dit cela d'un coup d'oeil ; « exFAT » ne le dit
            # pas, et les deux ensemble ne tiennent pas dans 180 px. La donnee
            # garde le format, l'etiquette garde ce qui discrimine.
            link_fmt = link_fmt.replace(" · exFAT", "").replace("exFAT · ", "")
        if court:
            link_fmt = f"{link_fmt} · {court}" if link_fmt else court
        elif "BP" in link_fmt and classe == "correctif":
            # Taille inconnue mais on sait que ce n'est pas le jeu : « fix » le
            # dit, faute de mieux.
            link_fmt = f"{link_fmt} · fix"
        tag = " · ".join(p for p in (link_fmt, link_region,
                                     f"v{version_utile}" if version_utile else "") if p)
        if not tag and link_version:
            link_version = _abrege.get(link_version, link_version)
            # Ni format ni region : sans la version, l'etiquette dirait seulement
            # l'hebergeur, deja affiche dessous. On la remet.
            tag = f"v{link_version}"
        # L'app affiche l'hote sous chaque ligne (.download-link-host) : repeter
        # « Viki » au-dessus de « vikingfile.com » coute des pixels pour rien.
        # Mesure du 2026-08-30 sur 15743 liens : la troncature tombe de 19 % a
        # 8 %. Et l'ambiguite ne suit pas — en comptant l'hote, ce que voit
        # l'utilisateur, il ne reste que 2 paires indiscernables, toutes deux
        # sur link-vault.org, qui n'heberge meme pas de fichiers.
        link["name"] = f"[{tag}]" if tag else (base or "")
    # Archives découpées : « …part01.rar », « …part02.rar »… produisaient N
    # libellés IDENTIQUES (12 mesurés sur Marvels Spider Man 2, PPSA03016), ce
    # qui donne l'impression de doublons alors que ce sont N fichiers dont il
    # faut la TOTALITÉ. Le numéro est dans l'URL, jamais dans le nom : on le
    # remonte, avec le total, pour qu'un manquant se voie.
    _number_parts(pkg)

    # Legende. L'etiquette abrege « Backport » en « BP » faute de place ; on
    # l'explique dans la description, EN PLUS de ce qu'elle porte deja (la ligne
    # « Format: … », qui, elle, garde le mot entier). Ajoutee seulement si une
    # etiquette de cette fiche emploie l'abreviation, et retiree en tete de
    # traitement a chaque run, donc idempotente.
    if any("BP" in (l.get("name") or "") for l in pkg.get("downloadLinks") or []):
        pkg["description"] = ((pkg.get("description") or "") + "\n" + _LEGENDE_BP).strip("\n")

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


def _mots(texte) -> set:
    return {m for m in re.split("[^a-z0-9]+", (texte or "").lower()) if len(m) > 2}


def _replacer_liens_par_nom(packages: list, stats: dict) -> None:
    """Remet a leur fiche les liens dont le NOM DE FICHIER nomme un autre jeu.

    Decouvert le 2026-08-30 en regardant « DOOM Eternal » : sa fiche portait des
    liens vers Superliminal, Death Stranding, Eriksholm et Shin Megami Tensei.
    Les 371 liens etrangers reperes plus tot par editionId n'avaient pas de
    cause tracable ; les noms releves chez les hebergeurs les rendent visibles.

    On n'agit QUE sur deux preuves concordantes : le nom porte un titleId
    different de la fiche, ET il evoque le titre de la fiche que ce titleId
    designe. Mesure sur les 9963 liens dont le nom porte un titleId :
      214  meme jeu, autre edition ... on ne touche pas
      414  autre jeu identifie ...... 376 deja presents sur la bonne fiche
                                      (purges), 38 absents (deplaces)
      667  indetermine .............. on ne touche pas
    Le doute ne se resout pas en supprimant : sans les deux preuves, le lien
    reste ou il est.
    """
    par_tid = {}
    for pkg in packages:
        t = (pkg.get("titleId") or "").strip().upper()
        if t:
            par_tid[t] = pkg
    purges = deplaces = 0
    for pkg in packages:
        tid = (pkg.get("titleId") or "").strip().upper()
        if not re.fullmatch("[A-Z]{4}[0-9]{3,}", tid):
            continue
        mots_fiche = _mots(pkg.get("title"))
        gardes = []
        for link in pkg.get("downloadLinks") or []:
            nom = link.get("fileName")
            m = _RE_TID_NOM.search(nom or "")
            autre = m.group(0).upper() if m else ""
            cible = par_tid.get(autre) if autre and autre != tid else None
            mots_nom = _mots(nom)
            # Le nom evoque le titre de CETTE fiche : meme jeu, autre edition.
            if cible is None or (mots_fiche & mots_nom):
                gardes.append(link)
                continue
            # ... et il evoque bien le titre de la fiche visee ?
            if not (_mots(cible.get("title")) & mots_nom):
                gardes.append(link)
                continue
            urls = {(x.get("url") or "") for x in (cible.get("downloadLinks") or [])}
            if (link.get("url") or "") in urls:
                purges += 1
            else:
                cible.setdefault("downloadLinks", []).append(link)
                deplaces += 1
        pkg["downloadLinks"] = gardes
    stats["liens_egares_purges"] = purges
    stats["liens_egares_deplaces"] = deplaces


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
    # AVANT la purge par editionId : celle-ci ne voit que les liens dont
    # toutes les occurrences portent un editionId decidable. Le nom de fichier
    # releve chez l'hebergeur en voit d'autres, et il dit OU ils devraient
    # etre — ce que l'editionId ne dit pas.
    _replacer_liens_par_nom(packages, stats)
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
