# Méthode de calcul des résultats

## Principe

L’application ne calcule jamais automatiquement un niveau de risque global. Le niveau Faible, Modéré, Important ou Critique est choisi manuellement par l’analyste et historisé avec sa justification, sa date et son auteur.

## Questionnaire Business Owner V4

Les nouvelles évaluations BO utilisent la méthode versionnée `BO_V4 4.0.0`. Elle produit deux profils CIA indépendants, sur une échelle de 0 à 5 :

- besoins de protection `B(C)`, `B(I)` et `B(D)` ;
- impacts métier `M(C)`, `M(I)` et `M(D)` ;
- `M(D, 7 jours)` est conservé comme indicateur complémentaire distinct.

Chaque indicateur retient le maximum des notes directes connues parmi les questions applicables. Pour un choix multiple, la note de la question est elle-même le maximum des modalités sélectionnées. Il n’existe ni moyenne, ni pondération, ni note CIA globale, ni ajustement par les volumes, les contrôles, l’exposition ou la maîtrise.

`ND` et une absence de réponse restent des informations manquantes. `NA` et une condition non déclenchée sont exclues. Un zéro numérique est une valeur valide. Sans réponse directe connue, l’indicateur est « Non évalué ». Une valeur calculée alors qu’une réponse directe applicable manque ou vaut `ND` est « Provisoire ».

La couverture est calculée séparément pour chaque indicateur : questions directes applicables renseignées / questions directes applicables. Les réponses `NA` sont exclues du dénominateur.

## Questionnaires IT

Pour chaque section, l’« indicateur moyen d’écart de contrôle » est la moyenne arithmétique des notes numériques des réponses applicables et finales. Cet indicateur n’est pas un niveau de risque.

- Les réponses ND, NA et les questions sans score sont exclues du dénominateur et comptées séparément.
- Pour une question à choix multiples notés, le maximum des notes sélectionnées est retenu, jamais leur somme.
- Les questions contextuelles restent visibles mais ne contribuent à aucun score si leurs options ne comportent pas de note.
- Seules les réponses applicables au périmètre final sont conservées comme réponses finales.

Les calculs sont centralisés dans `assessments/bo_scoring_v4.py`, `assessments/bo_scoring.py` et `assessments/services.py`.
