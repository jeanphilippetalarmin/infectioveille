"""Tests sans Internet: archives et lecture des flux. Exécuter: python scripts/test_update.py"""
from __future__ import annotations
import copy
import datetime as dt
import json
from pathlib import Path
import update

BASE = json.loads((Path(__file__).parents[1] / 'data' / 'veille.json').read_text())
NEWS = {
    'id':'auto-pmid-123456','date':'2026-10-26','titre':'Test de métadonnées PubMed (simulation)',
    'resume':'Référence factice uniquement utilisée dans un test, jamais publiée.',
    'impact_pratique':'Aucune interprétation', 'niveau_impact':1,'categorie':'Publication',
    'pathologie':'Tuberculose','source':'PubMed / Clinical Infectious Diseases — PMID 123456',
    'lien':'https://pubmed.ncbi.nlm.nih.gov/123456/'
}
update.TODAY=dt.date(2026,10,26)
update.MONDAY=dt.date(2026,10,26)
update.NOW=dt.datetime(2026,10,26,8,tzinfo=dt.timezone.utc)
d=update.update_data(copy.deepcopy(BASE),[NEWS],[],1,[])
assert d['nouvautes']['semaine']=='2026-10-26'
assert d['archives'][0]['semaine']=='2026-10-19'
assert len(d['archives']) == len(BASE['archives']) + 1
assert d['nouvautes']['nouveautes'][0]['id']=='auto-pmid-123456'
assert len(d['publications']) == len(BASE['publications']) + 1
# Une seconde collecte de la même semaine ne duplique ni la semaine ni l'article.
d2=update.update_data(copy.deepcopy(d),[NEWS],[],1,[])
assert len(d2['archives']) == len(d['archives'])
assert len(d2['nouvautes']['nouveautes'])==1
# Si les sources répondent mais n'ont aucune nouveauté, conserver une édition vide, datée.
update.TODAY=dt.date(2026,11,2)
update.MONDAY=dt.date(2026,11,2)
update.NOW=dt.datetime(2026,11,2,8,tzinfo=dt.timezone.utc)
d3=update.update_data(copy.deepcopy(d2),[],[],1,[])
assert d3['nouvautes']['semaine']=='2026-11-02'
assert d3['nouvautes']['nouveautes']==[]
assert len(d3['archives'])==len(d2['archives'])+1
assert d3['archives'][0]['semaine']=='2026-10-26'
# Le flux RSS ne transmet que les éléments de métadonnées, jamais du HTML exécutable.
xml=b'<rss><channel><item><title>Dengue France</title><link>https://www.santepubliquefrance.fr/test</link><pubDate>Thu, 22 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
assert update.iter_feed_entries(xml)[0]['title']=='Dengue France'
assert update.official_url('https://www.santepubliquefrance.fr/test','Santé publique France')
assert not update.official_url('https://example.com/test','Santé publique France')
print('Tests archivage, non-duplication, absence de nouveauté et flux RSS : OK')
