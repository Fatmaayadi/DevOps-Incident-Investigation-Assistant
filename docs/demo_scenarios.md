# Scénarios de démonstration

Durée conseillée : 12 à 15 minutes. Avant la démonstration :

1. Indexer la base : `python -m incident_assistant.indexing`. La commande doit afficher `29 documents and 2932 chunks`. Un index construit avant la correction des fiches (2926 chunks) est mis à jour automatiquement : seules les fiches modifiées sont réindexées.
2. Vérifier que `.env` contient `GROQ_API_KEY`. Une investigation consomme environ 4 000 tokens ; le quota gratuit est de 200 000 tokens par jour et par modèle.
3. Fermer tout autre processus qui utilise Qdrant : le mode embarqué n'accepte qu'un processus à la fois.

## 1. Incident Kubernetes classique (interface Web, environ 4 min)

`streamlit run app/streamlit_app.py`, puis saisir :

> After deploying version 2.4 our pods restart in a loop and kubectl shows CrashLoopBackOff.

À montrer :
- **Analyse** : la technologie, le symptôme et le message d'erreur `CrashLoopBackOff` sont extraits, et la mise à jour 2.4 est repérée comme changement récent.
- **Causes possibles** : chaque cause porte son statut (documentée / hypothèse) et ses citations `[S1]`…
- **Investigation** : les commandes (`kubectl describe pod`, `kubectl logs --previous`) viennent des passages cités.
- **Sources** : le texte exact de chaque passage, avec sa fiche et sa section ou son livre et sa page PDF.
- **Trace** : les nœuds LangGraph visités, les requêtes générées, les scores du cross-encoder et la décision d'évaluation des preuves (au moins 3 passages ≥ -2,86). La ligne `hybrid_retrieve` indique `(RRF order)`, l'ordre par défaut.
- **Feedback** : sous la réponse, cliquer sur 👍 *Useful*. Le message de confirmation apparaît et le compteur de la barre latérale se met à jour. Un second clic sur 👎 remplace le vote au lieu d'en ajouter un : une réponse ne compte qu'une fois. L'encadré *Detailed feedback* permet d'indiquer si le diagnostic est correct, si les sources sont pertinentes, quelle solution n'a pas fonctionné et la correction. Tout est enregistré dans la base locale `storage/assistant.db`, non versionnée, puis visible sur la page *Dashboard*.

## 2. Message d'erreur exact : intérêt de BM25 (environ 1 min 30)

> terraform init on our Mac fails with Failed to install provider: the package doesn't match any of the checksums previously recorded in the dependency lock file.

Point à faire remarquer : l'agent d'analyse reprend le message d'erreur mot pour mot comme requête, et BM25 retrouve la fiche *Terraform init Errors*. Pour approfondir, montrer dans `evaluation/results/retrieval_per_question_baseline.csv` la ligne `tf-004` pour chaque stratégie.

## 3. Description trop vague : demande de précisions (environ 1 min)

> my app is broken

L'assistant ne lance pas de recherche. Il pose des questions (messages d'erreur, technologie, changements récents) : c'est la branche `ask_clarification` du graphe.

## 4. Hors périmètre : signalement de l'insuffisance (environ 1 min 30)

> Our Kafka consumer group keeps rebalancing every few minutes and the lag grows.

Comportement attendu : le cross-encoder donne des scores bas aux passages, les requêtes sont reformulées deux fois au maximum, puis la réponse est marquée *insufficient evidence*. Les causes y apparaissent comme des hypothèses. Montrer la boucle bornée dans l'onglet Trace.

Les 5 incidents hors périmètre du test ont tous été traités ainsi par le système final (workflow complet).

## 5. MCP et Tool Calling (environ 3 min)

```bash
python scripts/mcp_client_demo.py
python scripts/mcp_agent_demo.py "Our Terraform pipeline was cancelled during apply and now every run says the state is locked. What should we do?"
```

À montrer :
1. Le client découvre les deux outils, appelle `search_knowledge_base` puis `get_document_metadata`, et reçoit une erreur MCP propre pour un identifiant inconnu.
2. L'agent décide **lui-même** d'appeler l'outil MCP (`-> tool call: search_knowledge_base(...)`), puis répond en citant la fiche.

En option : `npx @modelcontextprotocol/inspector python -m incident_assistant.mcp_server` pour présenter l'inspecteur officiel.

## 6. Reranking : avant / après (environ 2 min)

Fermer Streamlit (mode embarqué : un seul processus), puis :

```bash
python -m evaluation.compare_reranking "terraform apply fails because it cannot acquire the state lock"
```

À montrer : la colonne de gauche donne les 6 passages dans l'ordre RRF, celle de droite les 6 passages choisis par le cross-encoder parmi les 20 meilleurs candidats, avec leur rang RRF d'origine et leur score. Les deux dernières lignes indiquent le passage ajouté et le passage écarté par le reranker.

En option, mettre `RERANK_PASSAGES=true` dans `.env` et relancer l'interface. La trace indique alors `(reranked)`, et l'onglet Sources affiche le « rank before reranking » de chaque passage. L'option est désactivée par défaut : le système évalué (section suivante) garde l'ordre RRF.

## 7. Résultats du benchmark (environ 2 min)

Ouvrir `evaluation/results/README.md`, généré par `python -m evaluation.make_report`. Dans ce fichier, les sections « results of the final system » présentent le système final, et les sections « results of the earlier configuration » la configuration antérieure comparée :

- le tableau BM25 / sémantique / hybride / hybride + reranker, et le graphique Recall@k. Sur requêtes brutes, RRF seul obtient le meilleur MRR (0,990 contre 0,951 avec le reranker) ; sur les requêtes de l'agent, le reranker obtient 0,965 contre 0,941. Le système final garde l'ordre RRF, moins coûteux, et réserve le cross-encoder à la notation des preuves ; le reranking reste disponible en option (section 6) ;
- les métriques de génération du système final mesurées par le juge LLM, et leur comparaison avec la configuration antérieure : correctness et faithfulness progressent, context relevance et source match baissent ;
- l'expérience de fine-tuning (avant / après) ;
- les limites : biais d'auteur (fiches et questions écrites par la même équipe), jugement au niveau du document, petite taille du jeu.

## Option : déploiement Docker (environ 1 min, si le temps le permet)

À préparer avant la séance, car l'indexation dans le conteneur prend environ 15 minutes sur CPU avec les PDF :

```bash
docker compose build
docker compose --profile init run --rm indexer     # doit afficher 29 documents and 2932 chunks
```

Pendant la démonstration :

```bash
docker compose up -d
docker compose ps        # qdrant et app : (healthy)
```

À montrer : l'interface sur http://localhost:8501, servie par le conteneur. Elle communique avec le conteneur Qdrant (`http://qdrant:6333`). La clé Groq vient de `.env` au démarrage, sans être copiée dans l'image. Le feedback est conservé dans un volume. La CI GitHub Actions (`.github/workflows/ci.yml`) est configurée pour construire la même image et vérifier les deux healthchecks à chaque push.

## Questions probables et éléments de réponse

| Question | Réponse courte |
|---|---|
| Pourquoi deux agents seulement ? | Ce sont les deux seules étapes qui demandent du raisonnement (comprendre l'incident, construire le diagnostic). Les autres étapes sont du code déterministe : construction des requêtes, recherche, contrôle des preuves, validation des citations. |
| Pourquoi RRF ? | Les scores cosinus et BM25 n'ont pas la même échelle. RRF n'utilise que les rangs, n'a qu'un paramètre (k = 60) et ne demande aucun apprentissage. |
| Pourquoi ne pas ordonner les passages avec le reranker ? | Sur requêtes brutes, il fait baisser le MRR (0,951 contre 0,990) et coûte plus de 20 fois plus. Sur les requêtes de l'agent, il l'améliore légèrement (0,965 contre 0,941), pour un temps près de 5 fois supérieur. Sur 48 questions, cet écart ne permet pas de conclure : nous avons gardé l'ordre RRF par défaut, moins coûteux. Le reranking est disponible en option (`RERANK_PASSAGES=true`) et comparable question par question avec `evaluation.compare_reranking`. |
| Que devient le feedback ? | Une évaluation par réponse (une nouvelle évaluation remplace l'ancienne), enregistrée dans la base SQLite locale `storage/assistant.db` avec la question, la date, le statut, les causes, les documents cités et la configuration RAG. Le texte des passages et la clé ne sont jamais enregistrés. Le dashboard en tire les indicateurs ; `python -m incident_assistant.feedback --export-candidates FICHIER` extrait les cas à relire avant de les ajouter au jeu d'évaluation. Aucun entraînement n'est lancé automatiquement. |
| Comment la qualité de la base est-elle contrôlée ? | `python scripts/validate_knowledge_base.py` vérifie le manifeste (fichiers, empreintes SHA-256, doublons), les métadonnées, la structure des 11 sections, les citations et les liens entre fiches. Il renvoie un code d'erreur en cas de problème bloquant. |
| Comment avez-vous choisi le seuil de preuves ? | Sur un jeu de validation de 70 questions distinct du test (section 13.4 du rapport), et non sur les questions d'évaluation. |
| Le système final est-il meilleur que la configuration antérieure ? | En partie. Correctness (0,830 à 0,895) et faithfulness (0,584 à 0,679) progressent, mais context relevance (0,709 à 0,660) et source match (0,927 à 0,907) baissent, et le gain d'acceptation n'est que d'un incident sur 48. Trois éléments ont changé en même temps : aucun écart ne peut être attribué à un seul. |
| Comment évitez-vous les citations inventées ? | Les citations sont des champs structurés. `format_answer` retire tout identifiant qui ne correspond pas à un passage fourni, et rétrograde en « hypothèse » une cause qui n'a plus de citation valide. |
| Le système affirme-t-il avoir vérifié l'environnement ? | Non : le prompt l'interdit, et l'interface le rappelle en permanence. |
