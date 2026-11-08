# Orivane ISRA

Application Django en français présentant un processus complet d’Information Security Risk Assessment pour l’entreprise fictive Orivane Distribution. Elle sépare les besoins et impacts métier, les faiblesses des contrôles techniques, les scénarios de risque et l’appréciation globale décidée par l’analyste GRC.

## État actuel de la démonstration

La base `db.sqlite3` fournie contient les données de démonstration actuellement utilisées :

- 10 applications ;
- 10 campagnes terminées ;
- 20 questionnaires attribués ;
- 1 536 réponses ;
- 50 scénarios de risque ;
- 10 appréciations globales ;
- 10 comptes actifs.

Ces données sont conservées lors d’un lancement normal et lors de l’exécution de `python manage.py migrate`.

La base active `db.sqlite3` est volontairement incluse dans le dépôt afin qu’un recruteur puisse lancer le projet et examiner immédiatement les campagnes, réponses, calculs, scénarios et appréciations. Les anciennes bases `db.before-*.sqlite3` sont uniquement des points de restauration locaux et ne sont pas versionnées. Le fichier `.env`, l’environnement `.venv` et les caches restent également exclus du dépôt.

## Installation et lancement

Prérequis : Python 3.10 ou plus récent.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

Ouvrir ensuite :

- présentation : `http://127.0.0.1:8000/` ;
- connexion directe : `http://127.0.0.1:8000/connexion/`.

Il ne faut pas exécuter `python manage.py seed_demo` pour un lancement normal : cette commande réinitialise volontairement le référentiel et supprime les campagnes, attributions, réponses, demandes d’aide, scénarios et appréciations existants.

## Configuration

Django lit les variables du processus :

- `DJANGO_SECRET_KEY` ;
- `DJANGO_DEBUG` ;
- `DJANGO_ALLOWED_HOSTS` ;
- `DJANGO_SECURE_SSL_REDIRECT`.

Le projet peut démarrer localement avec les valeurs de développement définies dans `settings.py`. Pour une utilisation en production, fournir une clé secrète, définir `DJANGO_DEBUG=0`, configurer les hôtes autorisés et activer HTTPS.

Le fichier `.env` sert à l’environnement de développement configuré dans VS Code. Dans un terminal PowerShell indépendant, les variables nécessaires doivent être exportées dans le processus, par exemple :

```powershell
$env:DJANGO_SECRET_KEY="une-cle-secrete"
```

## Comptes disponibles

Mot de passe commun : `OrivaneDemo!2026`.

Les dix comptes ci-dessous sont actifs et leur authentification a été vérifiée. Ils ne disposent pas des droits d’administration Django.

| Identifiant | Personne | Fonction | Accès applicatif |
|---|---|---|---|
| `demo_dsi` | Claire Moreau | DSI | Analyste |
| `demo_rssi` | Thomas Perrin | RSSI | Analyste |
| `demo_grc` | Julie Bernard | Analyste sécurité et conformité | Analyste |
| `demo_it_app` | Nicolas Garnier | Responsable applications métier | Responsable IT Application |
| `demo_infra` | Sophie Lambert | Responsable infrastructure | Responsable IT Application |
| `demo_bo` | Élodie Martin | Directrice financière | Business Owner |
| `demo_ops` | Karim Benali | Directeur des opérations | Business Owner |
| `demo_commercial` | Antoine Lefèvre | Directeur commercial | Business Owner |
| `demo_rh` | Camille Dubois | Responsable RH | Business Owner |
| `demo_qualite` | Marc Delmas | Responsable qualité et traçabilité | Business Owner |

## Parcours applicatif

1. Un analyste ouvre une application et crée une campagne ISRA.
2. Il attribue un questionnaire BO V4 à un Business Owner et/ou un questionnaire IT Application V4 à un responsable technique.
3. Le répondant complète, sauvegarde puis soumet son questionnaire. Une demande d’aide compte comme traitement de la question concernée.
4. Après soumission, l’analyste consulte les résultats, exporte le XLSX et documente les scénarios de risque.
5. L’enregistrement d’une appréciation globale fait automatiquement passer la campagne au statut « Terminée ».

Pour une même application, seule la campagne terminée ayant reçu l’appréciation la plus récente reste modifiable. Les campagnes terminées antérieures sont conservées en lecture seule. Une campagne terminée ne peut plus recevoir de nouvelle attribution, mais l’appréciation de la dernière campagne terminée peut être révisée sans écraser son historique.

## Questionnaires et calculs

### Business Owner V4

- 86 questions et 445 modalités ;
- références stables `Q-001` à `Q-086` ;
- source unique : `docs/sources/Orivane_Questionnaire_ISRA_BO_V4.pdf` ;
- modèle de calcul `BO_V4 4.0.0` ;
- maxima directs séparés pour B(C/I/D) et M(C/I/D) ;
- indicateur complémentaire M(D, 7 jours) ;
- aucune moyenne, pondération ou note de risque globale automatique.

Les conditions de visibilité sont : Q-015 après Q-014, Q-024 à Q-026 après Q-023, Q-059 et Q-060 après Q-058, et Q-072 après Q-071.

### IT Application

- 82 questions dans le questionnaire V4 attribuable ;
- 74 questions communes et 8 questions activées pour une solution sous maîtrise technique de l’entreprise ;
- indicateurs de faiblesse calculés par famille de contrôles ;
- le questionnaire IT Application V2 est conservé uniquement pour l’historique et n’est pas proposé lors d’une nouvelle attribution.

L’application ne calcule jamais automatiquement le niveau de risque global. Le niveau Faible, Modéré, Important ou Critique est choisi et justifié par l’analyste.

Voir également :

- `docs/METHODE_CALCUL.md` ;
- `docs/COUVERTURE_QUESTIONNAIRES.md`.

## Autorisations et conservation

- Un répondant ne voit que ses propres attributions.
- Les scores, résultats et exports sont réservés aux analystes.
- L’analyste ne peut consulter les réponses qu’après leur soumission.
- Un questionnaire soumis est verrouillé pour le répondant.
- Les réponses devenues hors périmètre restent dans le brouillon, puis sont retirées des données actives lors de la soumission.
- Les résultats BO et IT V4 soumis sont historisés avec la version du modèle de calcul.
- Les exports XLSX neutralisent les préfixes pouvant être interprétés comme des formules Excel.

## Commandes de gestion

Appliquer les évolutions de structure sans réinitialiser les données :

```powershell
python manage.py migrate
```

Synchroniser BO V4 dans une base existante :

```powershell
python manage.py install_bo_v4
```

Importer ou actualiser les cinq scénarios StockFlow dans sa campagne la plus récente :

```powershell
python manage.py import_stockflow_scenarios
```

Une campagne précise peut être ciblée avec `--campaign-id <id>`. La commande est idempotente pour les références `ISRA-SF-R01` à `ISRA-SF-R05`.

Réinitialisation destructive, à utiliser uniquement pour reconstruire volontairement une base vide de démonstration :

```powershell
python manage.py seed_demo
```

## Architecture

- `orivane_isra/` : configuration Django, routes principales et sécurité ;
- `assessments/` : modèles, formulaires, vues, calculs, imports, commandes et tests ;
- `assessments/data/` : registres structurés et données versionnées ;
- `templates/` : pages Django ;
- `static/` : styles de l’interface ;
- `docs/` : méthode, couverture et documents sources ;
- `db.sqlite3` : base actuelle de la démonstration.

## Tests et contrôles

```powershell
python manage.py check
python manage.py test
python manage.py check --deploy
```

La suite comporte actuellement 39 tests. Elle couvre notamment les imports, les calculs BO et IT V4, les règles de visibilité, les permissions, la soumission, les instantanés de résultats, les exports XLSX, les scénarios, la clôture des campagnes, la modification limitée à la dernière campagne terminée et le retour vers la connexion après déconnexion.

## Limites actuelles

- SQLite convient à cette démonstration locale, mais une base serveur est préférable pour un usage multi-utilisateur en production.
- L’appréciation globale reste une décision manuelle de l’analyste.
- Les informations techniques ou organisationnelles non documentées doivent être considérées comme inconnues, et non comme absentes.
