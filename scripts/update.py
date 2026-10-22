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
import json
import os
from pathlib import Path
import re
import sys
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
WINDOW_START = MONDAY
WINDOW_END = TODAY

# Ces flux proviennent des pages RSS officielles (non de listes tierces).
RSS_SOURCES = [
    ("Santé publique France", "France", "https://www.santepubliquefrance.fr/rss/974"),
    ("ECDC — mises à jour épidémiologiques", "Europe", "https://www.ecdc.europa.eu/en/taxonomy/term/1310/feed"),
    ("ECDC — bulletin des menaces sanitaires", "Europe", "https://www.ecdc.europa.eu/en/taxonomy/term/1505/feed"),
    ("ECDC — recommandations", "Europe", "https://www.ecdc.europa.eu/en/taxonomy/term/1301/feed"),
]

# Filtre de veille orienté pratique clinique, et non couverture exhaustive.
QUERIES = [
    ("Bactériémies et endocardites", '("Staphylococcus aureus" AND bacteremia) OR endocarditis OR "bloodstream infection"'),
    ("Antibiorésistance", 'antimicrobial resistance OR antimicrobial stewardship OR carbapenem-resistant'),
    ("Infections de l’immunodéprimé", 'febrile neutropenia OR venetoclax OR hematologic malignancy OR transplant infection'),
    ("Infections fongiques invasives", 'invasive aspergillosis OR invasive candidiasis OR fungal infection'),
    ("Tuberculose", 'tuberculosis OR multidrug-resistant tuberculosis'),
    ("VIH et IST", 'HIV OR pre-exposure prophylaxis OR syphilis OR gonorrhea'),
    ("Infections ostéo-articulaires", 'prosthetic joint infection OR osteomyelitis OR fracture-related infection'),
    ("Infections respiratoires", 'pneumonia OR influenza OR respiratory syncytial virus'),
    ("Infections urinaires et digestives", 'urinary tract infection OR Clostridioides difficile'),
]

# Revues d'intérêt. Cette liste est sélective (d'autres revues ne seront pas retenues).
JOURNALS = {
    'the new england journal of medicine': 5,
    'n engl j med': 5,
    'the lancet infectious diseases': 5,
    'lancet infectious diseases': 5,
    'the lancet': 5,
    'lancet (london, england)': 5,
    'clinical infectious diseases': 4,
    'clin infect dis': 4,
    'clinical microbiology and infection': 4,
    'journal of antimicrobial chemotherapy': 4,
    'j antimicrob chemother': 4,
    'the journal of infectious diseases': 3,
    'journal of infectious diseases': 3,
    'open forum infectious diseases': 3,
    'infectious diseases now': 3,
    'eurosurveillance': 4,
    'mmwr. morbidity and mortality weekly report': 3,
}

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
            records.append({'title': get('title'), 'url': get('link'), 'date': get('pubDate') or get('dc:date')})
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
                if not date or not WINDOW_START <= date <= TODAY or len(title) < 8 or not KEYWORDS.search(title):
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
                    'id': stable_id('auto-rss', url), 'date': date.isoformat(), 'titre': title,
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


def journal_score(name: str) -> int:
    normalized = plain(name).lower().strip(' .')
    return JOURNALS.get(normalized, 0)


def collect_publications() -> tuple[list[dict], int, list[str]]:
    gathered, successes, errors = {}, 0, []
    for topic, term in QUERIES:
        query = f'FIRST_PDATE:[{WINDOW_START.isoformat()} TO {TODAY.isoformat()}] AND SRC:MED AND ({term}) sort_date:y'
        url = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode(
            {'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': '16'}
        )
        try:
            result = json.loads(fetch(url).decode('utf-8'))
            successes += 1
            for a in (result.get('resultList') or {}).get('result') or []:
                pmid = str(a.get('pmid') or '').strip()
                if not pmid.isdigit(): continue
                date = valid_date(a.get('firstPublicationDate'))
                if not date or not WINDOW_START <= date <= TODAY: continue
                journal = (a.get('journalInfo') or {}).get('journal') or {}
                rev = plain(journal.get('title') or a.get('journalTitle') or '')
                jscore = journal_score(rev)
                if not jscore: continue
                title = plain(a.get('title') or '')
                if not title: continue
                study_type = article_type(a)
                bonus = 4 if study_type == 'Recommandation' else 3 if study_type == 'Essai randomisé' else 2 if 'Méta-analyse' in study_type else 0
                score = jscore + bonus
                existing = gathered.get(pmid)
                if existing and existing['score'] >= score: continue
                authors = plain(a.get('authorString') or '')
                first_author = authors.split(',')[0].split(' et al')[0] if authors else 'À compléter'
                # PubMed URL is derived from a PMID supplied directly by the indexed API.
                link = 'https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/'
                gathered[pmid] = {'score': score, 'topic': topic, 'pmid': pmid,
                                  'journal': rev, 'title': title, 'date': date.isoformat(),
                                  'first_author': first_author, 'type': study_type, 'link': link}
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.HTTPError) as ex:
            errors.append(f'Europe PMC {topic} : {str(ex)[:130]}')
    chosen = []
    by_topic = {}
    for p in sorted(gathered.values(), key=lambda a: (a['score'], a['date'], a['pmid']), reverse=True):
        if by_topic.get(p['topic'], 0) >= 2: continue
        by_topic[p['topic']] = by_topic.get(p['topic'], 0) + 1
        chosen.append(p)
        if len(chosen) == 8: break
    output = []
    for p in chosen:
        output.append({
            'id': 'auto-pmid-' + p['pmid'], 'date': p['date'],
            'titre': p['title'],
            'resume': f"Notice indexée dans PubMed : {p['first_author']}, {p['journal']}. Type : {p['type']}. Résultats et texte intégral non analysés automatiquement.",
            'impact_pratique': "Repérage bibliographique, pas une recommandation. Vérifier la méthode, les résultats et l'applicabilité clinique dans le texte intégral.",
            'niveau_impact': 1, 'categorie': 'Publication', 'pathologie': p['topic'],
            'source': f"PubMed / {p['journal']} — PMID {p['pmid']}", 'lien': p['link'],
            'auteur': p['first_author'], 'revue': p['journal'], 'type_etude': p['type'],
            'statut': 'Référencement automatique — non évalué',
        })
    return output, successes, errors


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
    items = sorted(found.values(), key=lambda x: x.get('date', ''), reverse=True)
    return items[:limit] if limit else items


def update_data(data: dict, news: list[dict], alerts: list[dict], n_sources: int, errors: list[str]) -> dict:
    d = TODAY.isoformat()
    data['derniere_tentative'] = d
    data['sources_automatiques'] = [name for name, _, _ in RSS_SOURCES] + ['Europe PMC / PubMed']
    data['erreurs_sources'] = errors[:18]
    date_key = MONDAY.isoformat()
    if not news and data['nouvautes'].get('semaine') == date_key:
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
            'resume': x['resume'], 'message_cle': x['impact_pratique'], 'lien': x['lien'],
            'acces': 'Métadonnées vérifiées via Europe PMC ; texte intégral non relu automatiquement.'
        })
    data['publications'] = merge_by_id(data['publications'], pub_items, limit=180)
    data['maj_auto'] = NOW.isoformat(timespec='seconds')
    data['etat_collecte'] = f"Métadonnées actualisées automatiquement le {d} ({len(news)} signalements, {n_sources} sources répondantes)."
    return data


def main() -> int:
    data = read_data()
    official, alertes, ok_feeds, errs1 = collect_official()
    papers, ok_pmc, errs2 = collect_publications()
    # Ne pas écraser une édition sourcée lors d'une panne généralisée.
    if ok_feeds == 0 and ok_pmc == 0:
        print('ERREUR: toutes les sources sont indisponibles ; contenu conservé.', file=sys.stderr)
        return 1
    # Équilibre : jusqu'à 4 bulletins institutionnels et 6 publications indexées.
    # Sans cette règle, un flux très actif pourrait masquer la bibliographie.
    found = merge_by_id([], official)[:4] + merge_by_id([], papers)[:6]
    found = merge_by_id([], found)[:10]
    data = update_data(data, found, alertes, ok_feeds + ok_pmc, errs1 + errs2)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Date {TODAY} · Flux officiels répondants {ok_feeds}/{len(RSS_SOURCES)} · requêtes Europe PMC {ok_pmc}/{len(QUERIES)} · nouveaux signalements {len(found)} · archives {len(data["archives"])}')
    for error in errs1 + errs2:
        print('Avertissement : ' + error, file=sys.stderr)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
