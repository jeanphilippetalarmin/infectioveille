"""Tests fonctionnels sans réseau du nouveau moteur de veille.
Exécution : python scripts/test_v3.py
"""
import copy
import datetime as dt
import json
from pathlib import Path
import urllib.parse
import update

BASE = json.loads((Path(__file__).parents[1] / 'data' / 'veille.json').read_text(encoding='utf-8'))
update.TODAY = dt.date(2026, 10, 23)
update.MONDAY = dt.date(2026, 10, 19)
update.WINDOW_START = update.TODAY - dt.timedelta(days=45)
update.NOW = dt.datetime(2026,10,23,11,0, tzinfo=dt.timezone.utc)
assert len(update.QUERIES) >= 15
assert len(update.GUIDELINE_INDEXES) >= 12
for name in ['Medical Mycology','Mycoses','Journal of Fungi (Basel, Switzerland)', 'Clinical Microbiology and Infection','Journal of Infection', 'Transplant Infectious Disease']:
    assert update.journal_score(name) > 0, name
assert update.journal_score('Journal inconnu') == 0
# Test sur un article vieux de 23 jours découvert le 23 octobre, et un duplicat connu.
old_title = BASE['publications'][0]['titre']
rec = dict(pmid='98765432', firstPublicationDate='2026-09-30', title='Invasive aspergillosis in hematological malignancies: a randomized trial',
           authorString='M. Auteur, Y. Auteur',abstractText='Introduction '*20,
           journalInfo={'journal':{'title':'Medical Mycology'}},pubTypeList={'pubType':['Randomized Controlled Trial']},doi='10.1000/test123')
known = dict(rec, pmid='98765431', title=old_title)
response={'resultList':{'result':[rec, known]}}
original_fetch = update.fetch
try:
    update.fetch=lambda url,**kw:json.dumps(response).encode()
    news,success,errs=update.collect_publications(BASE)
finally:
    update.fetch=original_fetch
assert success == len(update.QUERIES) and not errs, errs
assert len(news)==1, news
assert news[0]['id']=='auto-pmid-98765432'
assert news[0]['date']=='2026-09-30'
assert news[0]['date_detection']=='2026-10-23'
assert news[0]['pathologie'].startswith('Mycologie') or news[0]['pathologie'].startswith('Immunodéprimés')
assert 'impact_pratique' not in news[0]
d = update.update_data(copy.deepcopy(BASE),news,[],17,[],{})
assert any(x['id']=='auto-pmid-98765432' for x in d['nouvautes']['nouveautes']), 'Publication tardive non affichée'
assert any(x['id']=='auto-pmid-98765432' for x in d['publications'])
# Après intégration, mêmes réponses API : aucun doublon.
try:
    update.fetch=lambda url,**kw:json.dumps(response).encode()
    again,_,_=update.collect_publications(d)
finally:
    update.fetch=original_fetch
assert not again
# Surveillance catalogues : première visite = référence initiale, seconde visite
# identique = pas d'alerte, ajout d'un lien = changement non interprété.
def page(n):
    links=''.join(f'<a href="/guidelines/g-{i}">Guidelines for infection {i}</a>' for i in range(n))
    return ('<html><body>'+links+'</body></html>').encode()
assert update.guideline_fingerprint('https://www.example.org/guidelines',page(4))[1]==4
indexes = update.GUIDELINE_INDEXES
try:
    update.GUIDELINE_INDEXES=[('Exemple','International','https://www.example.org/guidelines')]
    update.fetch=lambda url,**kw:page(4)
    first,ok,errors,state=update.monitor_guidelines({})
    assert ok==1 and not first and not errors
    again,ok,errors,stable=update.monitor_guidelines({'suivi_recommandations':state})
    assert not again
    update.fetch=lambda url,**kw:page(5)
    changed,ok,errors,updated=update.monitor_guidelines({'suivi_recommandations':state})
    assert len(changed)==1 and 'non confirmée' in changed[0]['statut']
    assert changed[0]['date_type'].startswith('Date de détection')
    def fail(*a,**kw): raise OSError('simulation panne')
    update.fetch=fail
    alerts,ok,errors,st=update.monitor_guidelines({'suivi_recommandations':updated})
    assert not alerts and ok==0 and len(errors)==1
    assert list(st.values())[0]['empreinte']==list(updated.values())[0]['empreinte']
finally:
    update.GUIDELINE_INDEXES=indexes
    update.fetch=original_fetch
print('Tests V3 : revues, fenêtre glissante, déduplication, retard d’indexation, catalogues, panne : OK')
