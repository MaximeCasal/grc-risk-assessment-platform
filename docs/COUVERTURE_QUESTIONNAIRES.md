# Couverture des questionnaires

Les questionnaires utilisés sont intégrés dans leur totalité à partir des documents conservés dans `docs/sources/` : `Orivane_Questionnaire_ISRA_BO_V4.pdf` est l’unique référence du questionnaire Business Owner et permet sa reconstruction complète avec le registre structuré V4. `Questionnaire_ISRA_IT_Application_V2.pdf` reste la source distincte du questionnaire IT Application.

| Questionnaire | Questions intégrées | Logique principale |
|---|---:|---|
| ISRA Business Owner V4 | 86 sur 86, 445 choix | Nouveau parcours attribuable ; identifiants `Q-001` à `Q-086` et scoring B/M |
| ISRA IT Application V2 | 82 sur 82 | 74 questions dans le Socle commun et 8 spécifiques à la maîtrise technique |

## Business Owner

Le Socle commun est toujours affiché. Les catégories Finance, RH, Achats, Commerce, Logistique, Qualité, Administratif, Juridique, Intégrations SI, Identités et accès et Reporting peuvent être activées indépendamment.

Lorsqu’une question appartient à plusieurs catégories, une seule catégorie active suffit pour l’afficher. La question n’apparaît qu’une fois. Les sous-catégories servent uniquement à documenter le rattachement dans le PDF et ne deviennent pas des conditions supplémentaires.

Les niveaux de priorité éditoriaux du PDF ne sont pas affichés dans l’interface. Toutes les questions devenues applicables au périmètre sélectionné doivent être traitées avant soumission. Une question est considérée comme traitée lorsqu’elle possède une réponse ou lorsqu’une demande d’aide a été envoyée pour cette question.

Les conditions explicites suivantes sont appliquées : Q-015 après Q-014, Q-024 à Q-026 après Q-023, Q-059 et Q-060 après Q-058, Q-072 après Q-071.

Les questions V4 utilisent les références stables `Q-001` à `Q-086` et leurs modalités `Q-001#01`, etc. Le scoring réutilise directement la liste produite par le moteur de visibilité ci-dessus.

## IT Application

Le Socle commun contient 74 questions. Les 8 questions A02, A04, A08, F07, F08, F09, F10 et F11 apparaissent lorsque « Solution sous maîtrise technique de l’entreprise » est sélectionnée. Le PDF ne contient aucune question exclusivement SaaS : activer uniquement la famille SaaS conserve donc les 74 questions communes. Pour une solution hybride, les deux familles peuvent être sélectionnées simultanément.

## Fidélité des réponses

Les choix uniques, choix multiples, textes libres, notes numériques, réponses ND et NA sont importés depuis les PDF. Pour les choix multiples, « Je ne sais pas », « Aucune » et « Aucun » sont exclusifs des autres réponses lorsqu’ils sont incompatibles.
