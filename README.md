# InfectioVeille — site public avec veille documentaire automatique

Site médical **statique**, utilisable sur ordinateur et mobile, avec archives hebdomadaires et actualisation automatique une fois publié sur GitHub Pages.

## Mise en ligne (une seule fois)

1. Créer un compte GitHub si nécessaire, puis un dépôt public, idéalement nommé `infectioveille`.
2. Télécharger le fichier ZIP et **ajouter les fichiers/dossiers qui sont à l'intérieur du ZIP** à la racine de ce dépôt : `index.html`, `data/veille.json`, `scripts/update.py`, `.github/workflows/veille.yml` et `README.md`. Important : conserver l'arborescence, y compris le dossier `.github`.
3. Dans le dépôt, ouvrir **Settings → Pages → Build and deployment → Source → GitHub Actions**.
4. Dans **Settings → Actions → General → Workflow permissions**, s'assurer que l'automatisation peut écrire dans le dépôt (sur certaines configurations, choisir **Read and write permissions**). Le workflow demande explicitement `contents: write`, `pages: write` et `id-token: write`.
5. Ouvrir **Actions** et constater le déploiement déclenché par le premier envoi sur `main`. Il est aussi possible de lancer **Run workflow** manuellement.
6. L'adresse publique sera **`https://VOTRE_IDENTIFIANT.github.io/infectioveille/`** si le dépôt s'appelle `infectioveille` : remplacer `VOTRE_IDENTIFIANT` par le véritable nom de compte. Vérifier l'adresse réelle dans **Settings → Pages**, avant de la diffuser. Ce n'est **pas** une adresse active tant que vous n'avez pas publié le dépôt.

GitHub Pages permet également d'utiliser ultérieurement un nom de domaine personnalisé.

## Actualisation, archives et données locales

- Chaque jour à **07:17 UTC**, GitHub Actions interroge Europe PMC (notices PubMed) et des flux officiels Santé publique France et ECDC. À Paris : environ **08:17 en hiver / 09:17 en été**. Il peut y avoir un retard d'exécution chez GitHub.
- Le lundi, dès qu'au moins une référence nouvelle est reçue, l'ancienne semaine est archivée sans être modifiée. Les autres jours, la semaine en cours peut s'enrichir. Les archives restent dans `data/veille.json` ; il n'y a **pas de purge automatique**.
- Chaque édition dispose d'une URL directe du type `.../#archives/2026-10-12`.
- Une visite de page télécharge la dernière édition ; si la page reste ouverte, elle la vérifie toutes les 15 minutes. En cas d'échec réseau, l'édition initiale intégrée à `index.html` reste consultable.
- Les **favoris et notes** ne sont stockés que dans le navigateur local de chaque visiteur (`localStorage`). Ils ne deviennent jamais publics. Un import manuel de JSON ne modifie que le navigateur courant, **pas** le site des autres visiteurs.
- Les informations médicales personnelles ou nominatives ne doivent pas être saisies dans ce site partagé.

## Périmètre exact de l'automatisation

**Automatisé :**
- Repérage de publications récentes indexées dans PubMed via l'API Europe PMC, sélection par requêtes thématiques et revues d'intérêt.
- Repérage de mises à jour dans des flux RSS officiels ECDC et Santé publique France, avec contrôle HTTP des liens institutionnels.
- Répartition chronologique, ajout des sources/dates, archivage, déploiement public.

**Non automatisé / nécessitant une validation humaine :**
- Lecture critique des textes intégraux, résultats, pertinence clinique, recommandation thérapeutique et niveaux de preuve.
- Couverture exhaustive de toutes les revues et recommandations SPILF/HAS/IDSA/ESCMID/OMS (tous ne proposent pas de flux normalisé vérifié).
- Mise à jour des dates d'abstracts de chaque congrès, recommandations thématiques de référence et résumés de congrès.
- Vérification clinique des alertes signalées : une entrée RSS n'implique **pas** un risque élevé ou la nécessité d'une action immédiate.

Le niveau ★ automatiquement attribué signifie uniquement « **signalement à consulter** », pas un jugement clinique. L'étiquette « Référencement automatique — non évalué » indique cette limite sur chaque carte générée. Si une source est indisponible, aucune référence n'est inventée ; l'échec est enregistré. Si toutes les sources échouent, le job échoue et l'ancienne édition demeure publiée.

### Surveillance de la tâche

Aller dans **Actions → InfectioVeille – collecte et publication** pour consulter les exécutions et leurs éventuelles erreurs. GitHub peut désactiver automatiquement les workflows programmés d'un dépôt public sans activité pendant 60 jours : vérifier de temps en temps leur statut. Un changement d'API ou de flux RSS peut nécessiter une maintenance du script.

## Structure

- `index.html` : page HTML complète, CSS et JavaScript inclus, affichage hors connexion avec son édition initiale.
- `data/veille.json` : édition courante + archives + dernières publications, congrès et alertes, lues par la version hébergée.
- `scripts/update.py` : collecte et archivage depuis les sources officielles, Python standard uniquement (pas de clé secrète et pas de dépendance externe).
- `.github/workflows/veille.yml` : exécution quotidienne et publication.

Pour une vérification en local, ouvrir directement `index.html` (édition initiale) ou lancer un serveur local dans le répertoire du site (`python -m http.server 8000`) puis ouvrir `http://localhost:8000/` (lecture de `data/veille.json`).

## Références techniques

- API Europe PMC : https://europepmc.org/RestfulWebService
- Flux RSS ECDC : https://www.ecdc.europa.eu/en/rss-feeds
- Flux RSS Santé publique France : https://www.santepubliquefrance.fr/rss
- GitHub Pages / workflows personnalisés : https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- GitHub Actions, tâches planifiées : https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
