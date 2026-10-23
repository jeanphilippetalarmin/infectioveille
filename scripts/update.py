#!/usr/bin/env python3
"""Veille documentaire automatisée, sans interprétation clinique.

Sources : Europe PMC (notices indexées dans PubMed), flux RSS officiels
Santé publique France et ECDC. Ne jamais fabriquer résumé, résultats,
recommandations, échéances ou niveau de risque.
Exécution quotidienne via GitHub Actions, sans clé API ni dépendance externe.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "veille.json"
NOW = dt.datetime.now(ZoneInfo("Europe/Paris"))
TODAY = NOW.date()
MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())
# Fenêtre bibliographique glissante : 45 jours pour compenser les retards
# d'indexation, sans assimiler détection et publication.
BIBLIO_LOOKBACK_DAYS = 45
WINDOW_START = TODAY - dt.timedelta(days=BIBLIO_LOOKBACK_DAYS)
RSS_START = TODAY - dt.timedelta(days=14)
WINDOW_END = TODAY

# Ces flux proviennent des pages RSS officielles (non de listes tierces).
RSS_SOURCES = [
    ("Santé publique France", "France", "https://www.santepubliquefrance.fr/rss/974"),
    ("ECDC — mises à jour épidémiologiques", "Europe", "https://www.ecdc.europa.eu/en/taxonomy/term/1310/feed"),
    ("ECDC — bulletin des menaces sanitaires", "Europe", "https://www.ecdc.europa.eu/en/taxonomy/term/1505/feed"),
    ("ECDC — recommandations", "Europe", "https://www.ecdc.europa.eu/en/taxonomy/term/1301/feed"),
]

# Recherche documentaire, par thèmes. Les termes sont EN anglais, avec syntaxe
# explicite (OR, guillemets). Les requêtes n'excluent pas les articles
# indexés tardivement grâce à la fenêtre glissante de 45 jours.
QUERIES = [
    ("Bactériémies et endocardites", '"Staphylococcus aureus" AND bacteremia OR endocarditis OR "bloodstream infection"'),
    ("Bon usage des anti-infectieux", '"antimicrobial stewardship" OR "oral switch" OR "antibiotic duration" OR "beta lactam"'),
    ("Antibiorésistance", '"antimicrobial resistance" OR "carbapenem resistant" OR "ESBL" OR "Candida auris"'),
    ("Immunodéprimés et hématologie", '"febrile neutropenia" OR venetoclax OR "hematopoietic stem cell" OR "CAR T" OR "hematologic malignancy"'),
    ("Mycologie invasive", '"invasive aspergillosis" OR "invasive candidiasis" OR mucormycosis OR fusariosis OR "chronic disseminated candidiasis"'),
    ("Mycologie – diagnostic et antifongiques", '"antifungal resistance" OR "fungal diagnostics" OR "galactomannan" OR "beta D glucan" OR "azole prophylaxis" OR cryptococcosis'),
    ("Tuberculose et mycobactéries", 'tuberculosis OR "latent tuberculosis" OR "nontuberculous mycobacteria"'),
    ("VIH, PrEP et IST", 'HIV OR "pre-exposure prophylaxis" OR syphilis OR gonorrhea OR "Mycoplasma genitalium"'),
    ("Hépatites virales", '"hepatitis B" OR "hepatitis C" OR "hepatitis D" OR "hepatitis delta"'),
    ("Infections ostéo-articulaires", '"prosthetic joint infection" OR osteomyelitis OR "fracture related infection"'),
    ("Infections respiratoires", 'pneumonia OR influenza OR "respiratory syncytial virus" OR "SARS-CoV-2"'),
    ("Infections urinaires et digestives", '"urinary tract infection" OR "Clostridioides difficile" OR "intra-abdominal infection"'),
    ("Vaccinations", 'vaccination OR vaccine OR "immunization schedule"'),
    ("Arboviroses et infections émergentes", 'dengue OR chikungunya OR "West Nile virus" OR mpox OR "tick borne"'),
    ("Pathologie du voyageur", 'malaria OR schistosomiasis OR leishmaniasis OR "travel medicine"'),
    ("Infections associées aux soins", '"healthcare associated infection" OR "catheter-related" OR "infection prevention"'),
    ("Tularémie et zoonoses", 'tularemia OR Francisella OR brucellosis OR Q fever OR leptospirosis'),
]

# Pondération documentaire pour le tri, jamais un niveau de preuve.
# Ajouter les alias exacts renvoyés par Europe PMC ; les titres ne sont pas
# supposés orthographiés de la même manière dans toutes les notices.
JOURNALS = {
    'the new england journal of medicine':5, 'n engl j med':5,
    'the lancet':5,'lancet (london, england)':5,'the lancet infectious diseases':5,
    'lancet infectious diseases':5,'nature medicine':5,'nat med':5,
    'jama':5,'j am med assoc':5,'bmj':5,'annals of internal medicine':5,'plos medicine':5,
    'clinical infectious diseases':4,'clin infect dis':4,
    'clinical microbiology and infection':4,'clin microbiol infect':4,
    'journal of antimicrobial chemotherapy':4,'j antimicrob chemother':4,
    'journal of infection':4,'j infect':4,'eurosurveillance':4,
    'the journal of infectious diseases':4,'j infect dis':4,
    'emerging infectious diseases':4,'emerg infect dis':4,
    'clinical microbiology reviews':4,'clin microbiol rev':4,
    'antimicrobial agents and chemotherapy':4,'antimicrob agents chemother':4,
    'hiv medicine':4,'blood':4,'leukemia':4,
    'medical mycology':4,'med mycol':4,'mycoses':4,
    'open forum infectious diseases':3,'open forum infect dis':3,
    'infectious diseases now':3,'infect dis now':3,
    'international journal of infectious diseases':3,'int j infect dis':3,
    'infection':3,'infection control and hospital epidemiology':3,
    'journal of hospital infection':3,'j hosp infect':3,
    'clinical microbiology and infection reports':3,
    'journal of clinical microbiology':3,'j clin microbiol':3,
    'molecular diagnosis & therapy':3,'microbiology spectrum':3,'mb io':3,'mbio':3,
    'journal of the international aids society':3,'j int aids soc':3,
    'aids (london, england)':3,'aids':3,
    'european journal of clinical microbiology & infectious diseases':3,
    'european journal of clinical microbiology and infectious diseases':3,
    'transplant infectious disease':3,'transpl infect dis':3,
    'bone marrow transplantation':3,'bone marrow transplant':3,
    'travel medicine and infectious disease':3,'trav med infect dis':3,
    'tropical medicine & international health':3,'tropical medicine and international health':3,
    'plos neglected tropical diseases':3,'plos negl trop dis':3,
    'intensive care medicine':3,'critical care (london, england)':3,
    'the international journal of tuberculosis and lung disease':3,
    'international journal of tuberculosis and lung disease':3,
    'the international journal of tuberculosis and lung disease : the official journal of the international union against tuberculosis and lung disease':3,
    'tuberculosis (edinburgh, scotland)':3,
    'journal of fungi (basel, switzerland)':3,'journal of fungi':3,'j fungi (basel)':3,
    'mycopathologia':3,
    'medical mycology case reports':2,
    'journal of fungal biology':2,
    'current fungal infection reports':2,
    'mmwr. morbidity and mortality weekly report':3,
}

# Catalogues institutionnels accessibles directement : vérification des liens
# et recherche de changement de listes, sans attribuer de date de publication.
# La première collecte initialise seulement l'état de référence.
GUIDELINE_INDEXES = [
    ('SPILF','France','https://www.infectiologie.com/fr/recommandations.html'),
    ('HAS – vaccination','France','https://www.has-sante.fr/jcms/c_2742985/fr/vaccination'),
    ('IDSA','International','https://www.idsociety.org/practice-guideline/all-practice-guidelines/'),
    ('ESCMID','Europe','https://www.escmid.org/guidelines-journals/guidelines/published-guidelines/'),
    ('ECIL – hématologie','Europe','https://ecil-leukaemia.com/en/resources/publications'),
    ('ECIL – recommandations','Europe','https://www.ecil-leukaemia.com/en/resources/resources-ecil'),
    ('ECMM – mycologie','Europe','https://www.ecmm.info/guidelines/'),
    ('ISHAM – mycologie','International','https://www.isham.org/'),
    ('EACS – VIH','Europe','https://www.eacsociety.org/guidelines/eacs-guidelines/'),
    ('BHIVA – VIH','Europe','https://bhiva.org/clinical-guidelines/'),
    ('ANRS-MIE – VIH','France','https://anrs.fr/actualites/actualites/vih-nouvelles-recommandations-de-bonne-pratique/'),
    ('SF2H','France','https://www.sf2h.net/publications.html'),
    ('SFM – antibiogramme','France','https://www.sfm-microbiologie.org/categories/sections-gt/comite-de-lantibiogramme/'),
    ('OMS – recommandations','Monde','https://www.who.int/publications/who-guidelines'),
    ('NIH – VIH opportunistes','International','https://clinicalinfo.hiv.gov/en/guidelines'),
]

KEYWORDS = re.compile(
    r'(infection|infectious|influenza|grippe|covid|sars|rsv|vrs|bronchiolit|'
    r'dengue|chikungunya|west nile|arbovir|rougeole|measles|tubercul|'
    r'legionell|mpox|ebola|antimicrob|résistan|resistan|bactéri|bacter|'
    r'vaccin|pneumoni|sepsis|hepatit|hépatit|méning|mening|'
    r'palud|malaria|cholera|choléra|hiv|vih|infection respiratoire|'
    r'fungal|champignon|outbreak|épidémi|epidemi)', re.I)

UA = 'InfectioVeille/2.0 (+https://www.ebi.ac.uk/europepmc/webservices/rest/; public-source-metadata)'


def fetch(url: str, timeout: int = 20, method: str = 'GET') -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json, application/xml, application/rss+xml, */*'}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if not (200 <= response.status < 400):
            raise ValueError(f'HTTP {response.status} : {url}')
        return response.read(3_000_000)


def valid_date(raw) -> dt.date | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return dt.date.fromisoformat(raw[:10]) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw[:10]) else None
    except ValueError:
        return None


def rss_date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    value = valid_date(raw)
    if value:
        return value
    try:
        return email.utils.parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, IndexError):
        return None


def plain(s: str) -> str:
    s = re.sub(r'<[^>]+>', ' ', html.unescape(s or ''))
    return re.sub(r'\s+', ' ', s).strip()


def official_url(s: str, source: str) -> bool:
    """Refuse les liens non institutionnels, raccourcisseurs et liens non HTTPS."""
    try:
        p = urllib.parse.urlsplit(s)
        if p.scheme != 'https' or not p.hostname:
            return False
        host = p.hostname.lower()
        allowed = ('santepubliquefrance.fr',) if source.startswith('Santé') else ('ecdc.europa.eu',)
        return any(host == h or host.endswith('.' + h) for h in allowed)
    except (ValueError, AttributeError):
        return False


def check_link(url: str) -> bool:
    """Lien de référence confirmé par une requête HTTP ; une erreur exclut le lien."""
    for method in ('HEAD', 'GET'):
        try:
            fetch(url, timeout=9, method=method)
            return True
        except (OSError, ValueError, urllib.error.HTTPError):
            continue
    return False


def stable_id(prefix: str, source: str) -> str:
    return prefix + '-' + hashlib.sha256(source.encode('utf-8')).hexdigest()[:17]


def iter_feed_entries(raw: bytes) -> list[dict]:
    """RSS 2.0 et Atom; ne fait pas confiance au contenu HTML du flux."""
    root = ET.fromstring(raw)
    records = []
    rss = root.findall('.//item')
    if rss:
        for item in rss:
            get = lambda x: item.findtext(x, default='')
            records.append({'title': get('title'), 'url': get('link'), 'date': get('pubDate') or get('{http://purl.org/dc/elements/1.1/}date')})
        return records
    atom = '{http://www.w3.org/2005/Atom}'
    for entry in root.findall('.//' + atom + 'entry'):
        href = ''
        for lk in entry.findall(atom + 'link'):
            if lk.attrib.get('rel', 'alternate') == 'alternate' and lk.attrib.get('href'):
                href = lk.attrib['href']; break
        records.append({'title': entry.findtext(atom + 'title') or '',
                        'url': href,
                        'date': entry.findtext(atom + 'published') or entry.findtext(atom + 'updated') or ''})
    return records


def collect_official() -> tuple[list[dict], list[dict], int, list[str]]:
    news, alerts, successes, errors = [], [], 0, []
    for name, zone, feed in RSS_SOURCES:
        try:
            entries = iter_feed_entries(fetch(feed))
            successes += 1
            candidates = []
            for e in entries:
                date, title, url = rss_date(e.get('date')), plain(e.get('title', '')), e.get('url', '')
                if not date or not RSS_START <= date <= TODAY or len(title) < 8 or not KEYWORDS.search(title):
                    continue
                if not official_url(url, name):
                    continue
                candidates.append((date, title, url))
            for date, title, url in sorted(candidates, reverse=True)[:5]:
                if not check_link(url):
                    continue
                is_guide = ('recommandation' in title.lower() or 'guidance' in title.lower() or name.endswith('recommandations'))
                category = 'Recommandation' if is_guide else 'Alerte épidémio'
                entry = {
                    'id': stable_id('auto-rss', url), 'date': date.isoformat(), 'date_detection':TODAY.isoformat(), 'titre': title,
                    'resume': 'Publication institutionnelle récente repérée automatiquement. Les chiffres et conclusions nécessitent la lecture du bulletin officiel.',
                    'impact_pratique': 'Contrôler la zone, la période, la définition des cas et les mesures recommandées dans la source primaire avant application.',
                    'niveau_impact': 1, 'categorie': category, 'pathologie': 'Surveillance et recommandations',
                    'source': name, 'lien': url, 'statut': 'Référencement automatique — contenu non relu',
                }
                news.append(entry)
                if not is_guide:
                    alerts.append({
                        'id': stable_id('al-auto', url), 'titre': title, 'zone': zone,
                        'niveau': 'À qualifier', 'date': date.isoformat(),
                        'resume': 'Signal publié par une institution. Gravité et portée clinique à évaluer dans le bulletin primaire.',
                        'source': name, 'lien': url,
                        'statut': 'Référencement automatique — risque non évalué'
                    })
        except (OSError, ValueError, ET.ParseError, urllib.error.HTTPError) as ex:
            errors.append(f'{name} : {str(ex)[:130]}')
    return news, alerts, successes, errors


def article_type(record: dict) -> str:
    p = record.get('pubTypeList') or {}
    arr = p.get('pubType') if isinstance(p, dict) else []
    if isinstance(arr, str): arr = [arr]
    low = ' '.join(arr or []).lower()
    if 'randomized controlled trial' in low: return 'Essai randomisé'
    if 'meta-analysis' in low or 'systematic review' in low: return 'Méta-analyse ou revue systématique'
    if 'guideline' in low or 'practice guideline' in low: return 'Recommandation'
    return 'Article indexé (type non qualifié)'


def canonical(s: str) -> str:
    value = unicodedata.normalize('NFKD', plain(s).lower())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()


def journal_score(name: str) -> int:
    key = canonical(name)
    return next((v for k, v in JOURNALS.items() if canonical(k) == key), 0)


def known_publications(data: dict) -> tuple[set[str], set[str]]:
    items = list(data.get('publications') or []) + list(data.get('nouvautes', {}).get('nouveautes') or [])
    for a in data.get('archives') or []:
        items.extend(a.get('nouveautes') or [])
    ids = {str(a.get('id')) for a in items if isinstance(a, dict) and a.get('id')}
    titles = {canonical(a.get('titre', '')) for a in items if isinstance(a, dict) and a.get('titre')}
    return ids, titles


def first_author(record: dict) -> str:
    raw = plain(record.get('authorString') or '')
    return raw.split(',')[0].split(' et al')[0] if raw else 'À compléter'


def collect_publications(data: dict | None = None) -> tuple[list[dict], int, list[str]]:
    """Cherche 45 jours, dédoublonne par PMID et titre, et ne retient que les
    références encore absentes du site. Priorité documentaire, pas clinique.
    Les abstracts servent à détecter la disponibilité et des termes de design,
    jamais à rédiger des conclusions automatiques.
    """
    seen_ids, seen_titles = known_publications(data or {})
    gathered, successes, errors = {}, 0, []
    for topic, term in QUERIES:
        query = f'FIRST_PDATE:[{WINDOW_START.isoformat()} TO {TODAY.isoformat()}] AND SRC:MED AND ({term}) sort_date:y'
        url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode(
            {'query': query, 'format':'json', 'resultType':'core', 'pageSize':'50'})
        try:
            result = json.loads(fetch(url).decode('utf-8'))
            successes += 1
            for a in (result.get('resultList') or {}).get('result') or []:
                pmid = str(a.get('pmid') or '').strip()
                if not pmid.isdigit() or 'auto-pmid-'+pmid in seen_ids: continue
                date = valid_date(a.get('firstPublicationDate'))
                if not date or not WINDOW_START <= date <= TODAY: continue
                journal = (a.get('journalInfo') or {}).get('journal') or {}
                rev = plain(journal.get('title') or a.get('journalTitle') or '')
                score = max(journal_score(rev), journal_score(journal.get('medlineAbbreviation') or ''))
                if not score: continue
                title = plain(a.get('title') or '')
                if len(title) < 15 or canonical(title) in seen_titles: continue
                typ = article_type(a)
                # Désélection de certains types à risque de faire du bruit.
                types = ' '.join((a.get('pubTypeList') or {}).get('pubType') or []).lower()
                if 'retracted publication' in types or 'retraction of publication' in types: continue
                abstract = plain(a.get('abstractText') or '')
                has_abstract = len(abstract) >= 120
                # Pondération explicite, sans prétendre apprécier la validité des résultats.
                bonus = 5 if typ == 'Recommandation' else 4 if typ == 'Essai randomisé' else 3 if 'Méta-analyse' in typ else 0
                if has_abstract: bonus += 1
                if topic.startswith(('Mycologie','Immunodéprimés')): bonus += 2
                if 'case reports' in types: bonus -= 3
                rank = score + bonus
                old = gathered.get(pmid)
                if old and old['score'] >= rank: continue
                gathered[pmid] = dict(score=rank, topic=topic, pmid=pmid, journal=rev,
                    title=title, date=date.isoformat(), author=first_author(a), typ=typ,
                    abstract=has_abstract, doi=plain(a.get('doi') or ''))
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.HTTPError) as exc:
            errors.append(f'Europe PMC ({topic}) : {str(exc)[:130]}')
    # Un même article peut correspondre à plusieurs recherches : un seul
    # résultat et max 2 par thème, avec une diversité de sujets.
    chosen, by_topic, chosen_titles = [], {}, set()
    for x in sorted(gathered.values(), key=lambda a:(a['score'],a['date'],a['pmid']), reverse=True):
        if by_topic.get(x['topic'],0) >= 2 or canonical(x['title']) in chosen_titles: continue
        chosen.append(x)
        chosen_titles.add(canonical(x['title']))
        by_topic[x['topic']] = by_topic.get(x['topic'],0) + 1
        if len(chosen) >= 8: break
    output = []
    for x in chosen:
        output.append({
            'id':'auto-pmid-'+x['pmid'], 'date':x['date'], 'date_detection': TODAY.isoformat(), 'date_type':'Date de publication indexée',
            'titre':x['title'],
            'resume':f"{x['author']} · {x['journal']} · {x['typ']}. " + ('Résumé disponible dans la notice PubMed ; non interprété automatiquement.' if x['abstract'] else 'Résumé absent ou insuffisant dans la notice indexée.'),
            'niveau_impact':1, 'categorie':'Publication', 'pathologie':x['topic'],
            'source':f"Europe PMC / PubMed · PMID {x['pmid']}",
            'lien':f"https://pubmed.ncbi.nlm.nih.gov/{x['pmid']}/",
            'auteur':x['author'], 'revue':x['journal'], 'type_etude':x['typ'],
            'doi':x['doi'], 'resume_disponible':x['abstract'],
            'statut':'Détection bibliographique — résultats et texte intégral non évalués',
        })
    return output, successes, errors


class AnchorReader(HTMLParser):
    """Liens textuels normalisés pour détecter des changements durables
    dans les catalogues. Les liens éditoriaux restent non interprétés.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []
        self.href = None
        self.fragments = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','svg','noscript'): self.hidden += 1
        if tag == 'a' and self.hidden == 0:
            self.href = dict(attrs).get('href')
            self.fragments = []
    def handle_data(self, d):
        if self.href is not None and not self.hidden: self.fragments.append(d)
    def handle_endtag(self, tag):
        if tag in ('script','style','svg','noscript') and self.hidden: self.hidden -= 1
        if tag == 'a' and self.href is not None:
            self.entries.append((self.href, plain(' '.join(self.fragments))))
            self.href = None
            self.fragments = []


CATALOG_TERMS = re.compile(r'\b(guidelines?|guidance|recommandations?|recommendations?|avis|consensus|\brbp\b|\brpc\b|clinical practice|\becil\b|therapy|treatment|prophylaxis|vaccin|antifungal|antibiot|candid|aspergill|cryptococc|mucor|mycos|infection|vih|hiv|hepatit|sepsis|tubercul|prevention|prévention)\b',re.I)
PATH_TERMS = ('guideline','recommand','/publication','/practice','/clinical','/resources','/document','/pdf','/avis','/fiche')


def guideline_fingerprint(url: str, body: bytes) -> tuple[str, int]:
    reader = AnchorReader()
    reader.feed(body.decode('utf-8',errors='replace'))
    source = urllib.parse.urlsplit(url).hostname or ''
    tokens = set()
    for href,title in reader.entries:
        if len(title) < 8 or len(title) > 240 or not href: continue
        full = urllib.parse.urljoin(url,href)
        u = urllib.parse.urlsplit(full)
        host = (u.hostname or '').lower()
        if u.scheme != 'https' or not host or not (host == source or host.endswith('.'+source) or source.endswith('.'+host)):
            continue
        if not (CATALOG_TERMS.search(title) or any(t in u.path.lower() for t in PATH_TERMS)): continue
        if re.search(r'^(home|contact|login|politique|privacy|read more|en savoir plus|more info|download|télécharger)$', title, re.I): continue
        norm_url = urllib.parse.urlunsplit(('https',host,u.path.rstrip('/'),'', ''))
        tokens.add(norm_url + ' | ' + canonical(title)[:130])
    if len(tokens) < 3:
        raise ValueError(f'catalogue non exploitable : {len(tokens)} liens de référence')
    digest = hashlib.sha256('\n'.join(sorted(tokens)).encode('utf-8')).hexdigest()
    return digest, len(tokens)


def monitor_guidelines(data: dict) -> tuple[list[dict], int, list[str], dict]:
    """Surveillance de pages officielles par empreinte des liens pertinents.
    Une modification n'est PAS une recommandation nouvelle ; la date affichée
    est explicitement celle de la détection. Première visite = baseline.
    """
    old = data.get('suivi_recommandations') or {}
    state = dict(old)
    alerts, ok, errors = [], 0, []
    for nom, zone, url in GUIDELINE_INDEXES:
        key = stable_id('index',url)
        previous = old.get(key) or {}
        try:
            digest,count = guideline_fingerprint(url, fetch(url, timeout=14))
            ok += 1
            changed = bool(previous.get('empreinte') and previous['empreinte'] != digest)
            state[key] = {'nom':nom,'zone':zone,'lien':url,'empreinte':digest,
                          'nombre_liens':count,'dernier_controle':TODAY.isoformat(),
                          'dernier_changement':TODAY.isoformat() if changed else previous.get('dernier_changement'),
                          'statut':'Modification détectée – examen humain requis' if changed else 'Index vérifié – aucun changement détecté'}
            if changed:
                alerts.append({'id':stable_id('auto-guide',url+digest), 'date_detection':TODAY.isoformat(),
                    'date':TODAY.isoformat(), 'date_type':'Date de détection (pas date de publication)',
                    'titre':f'{nom} : modifications détectées dans le catalogue de recommandations',
                    'resume':'La liste des liens de référence de cette page officielle a changé depuis le dernier contrôle réussi. Nature, contenu et date des modifications non déterminés automatiquement.',
                    'niveau_impact':1,'categorie':'Recommandation','pathologie':'Recommandations et référentiels',
                    'source':nom,'lien':url,'statut':'Index modifié — nouvelle recommandation non confirmée'})
        except (OSError, ValueError, urllib.error.HTTPError) as ex:
            msg = str(ex)[:130]
            errors.append(f'Recommandations {nom} : {msg}')
            state[key] = {**previous, 'nom':nom,'zone':zone,'lien':url,
                          'statut':'Indisponible / analyse impossible', 'erreur':msg}
    return alerts,ok,errors,state


def read_data() -> dict:
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('nouvautes'), dict):
        raise ValueError('data/veille.json invalide : aucune modification.')
    for name in ('archives', 'publications', 'alertes', 'congres'):
        if not isinstance(data.get(name), list):
            raise ValueError(f'data/veille.json invalide : {name}')
    return data


def merge_by_id(existing: list[dict], new: list[dict], limit: int | None = None) -> list[dict]:
    found = {str(x['id']): x for x in existing if isinstance(x, dict) and x.get('id')}
    for x in new:
        found[str(x['id'])] = x
    items = sorted(found.values(), key=lambda x: (x.get('date_detection') or x.get('date', ''), x.get('date','')), reverse=True)
    return items[:limit] if limit else items


def update_data(data: dict, news: list[dict], alerts: list[dict], n_sources: int, errors: list[str], suivi: dict | None = None) -> dict:
    d = TODAY.isoformat()
    data['derniere_tentative'] = d
    data['sources_automatiques'] = [name for name, _, _ in RSS_SOURCES] + ['Europe PMC / PubMed'] + [name for name, _, _ in GUIDELINE_INDEXES]
    if suivi is not None: data['suivi_recommandations'] = suivi
    data['erreurs_sources'] = errors[:18]
    date_key = MONDAY.isoformat()
    if not news and data['nouvautes'].get('semaine') == date_key:
        data['maj_auto'] = NOW.isoformat(timespec='seconds')
        data['etat_collecte'] = 'Aucune nouvelle référence éligible : semaine en cours conservée.'
        return data
    current = data['nouvautes']
    if current.get('semaine') != date_key:
        archive = data['archives']
        if current.get('semaine'):
            archive = [current] + [x for x in archive if x.get('semaine') != current['semaine']]
        data['archives'] = sorted(archive, key=lambda x: x.get('semaine', ''), reverse=True)
        cards = news[:10]
    else:
        # Au cours de la même semaine, conserver les articles relus initialement,
        # tout en ajoutant les métadonnées documentaires auto-détectées.
        cards = merge_by_id(current.get('nouveautes', []), news, limit=10)
        # Les premières éditions manuelles étaient plus riches : ne pas les effacer.
    # Messages bibliographiques sans interprétation de résultats.
    three = [f"À examiner : « {x['titre']} » ({x['source']})." for x in cards[:3]]
    if not three:
        three = ["Aucune référence nouvelle conforme aux critères de collecte cette semaine ; consulter directement les sources officielles."]
    data['nouvautes'] = {
        'semaine': date_key,
        'fin': (MONDAY + dt.timedelta(days=6)).isoformat(),
        'maj': d,
        'messages_cles': three,
        'nouveautes': cards,
        'type_edition': 'Repérage automatisé non validé cliniquement',
    }
    # Conserver les alertes antérieures encore pertinentes à partir d'une
    # fenêtre de 45 jours, sans les présenter comme des alertes vérifiées en cours.
    oldest = TODAY - dt.timedelta(days=45)
    previous = [x for x in data['alertes'] if (valid_date(x.get('date')) or dt.date.min) >= oldest]
    data['alertes'] = merge_by_id(previous, alerts, limit=45)
    # Injecter les références automatiquement collectées dans la rubrique Publications.
    pub_items = []
    for x in news:
        if x['categorie'] != 'Publication': continue
        pub_items.append({
            'id': x['id'], 'date': x['date'], 'titre': x['titre'],
            'auteur': x.get('auteur', 'À compléter'), 'revue': x.get('revue', 'À compléter'),
            'type': x.get('type_etude', 'Article scientifique'), 'pathologie': x['pathologie'],
            'resume': x['resume'], 'message_cle': '', 'lien': x['lien'],
            'acces': 'Métadonnées vérifiées via Europe PMC ; texte intégral non relu automatiquement.'
        })
    data['publications'] = merge_by_id(data['publications'], pub_items, limit=180)
    data['maj_auto'] = NOW.isoformat(timespec='seconds')
    data['etat_collecte'] = f"Métadonnées actualisées automatiquement le {d} ({len(news)} signalements, {n_sources} sources répondantes)."
    return data


def main() -> int:
    data = read_data()
    official, alertes, ok_feeds, errs1 = collect_official()
    papers, ok_pmc, errs2 = collect_publications(data)
    guideline_news, ok_guides, errs3, suivi = monitor_guidelines(data)
    # Ne pas écraser une édition sourcée lors d'une panne généralisée.
    if ok_feeds == 0 and ok_pmc == 0 and ok_guides == 0:
        print('ERREUR: toutes les sources sont indisponibles ; contenu conservé.', file=sys.stderr)
        return 1
    # Équilibre : jusqu'à 4 bulletins institutionnels et 6 publications indexées.
    # Sans cette règle, un flux très actif pourrait masquer la bibliographie.
    found = merge_by_id([], guideline_news)[:2] + merge_by_id([], official)[:2] + merge_by_id([], papers)[:6]
    found = merge_by_id([], found)[:10]
    data = update_data(data, found, alertes, ok_feeds + ok_pmc + ok_guides, errs1 + errs2 + errs3, suivi)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Date {TODAY} · Flux {ok_feeds}/{len(RSS_SOURCES)} · PubMed {ok_pmc}/{len(QUERIES)} · catalogues {ok_guides}/{len(GUIDELINE_INDEXES)} · signalements {len(found)} · archives {len(data["archives"])}')
    for error in errs1 + errs2 + errs3:
        print('Avertissement : ' + error, file=sys.stderr)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
