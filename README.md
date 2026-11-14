# DevOps Incident Investigation Assistant

Projet de la matière **Programmation Python Data Science avancée**. L'assistant aide à investiguer un incident DevOps / Cloud décrit en langage naturel. Il :

- analyse l'incident ;
- recherche dans une base documentaire, en combinant recherche sémantique et BM25 ;
- propose des causes possibles, des étapes de diagnostic et des solutions, **chacune reliée à ses sources** (document + page ou section) ;
- signale clairement quand la documentation ne suffit pas.

## Fonctionnalités disponibles

Toutes les fonctionnalités ci-dessous ont été exécutées et testées sur la version actuelle du projet.

| Fonctionnalité | Point d'entrée |
|---|---|
| Interface Web : analyse, causes, investigation, sources, trace | `streamlit run app/streamlit_app.py` |
| Ligne de commande | `python scripts/ask.py "<incident>"` |
| Serveur MCP, avec un client et un agent de démonstration | `incident_assistant/mcp_server.py`, `scripts/mcp_client_demo.py`, `scripts/mcp_agent_demo.py` |
| Indexation incrémentale de la base (6 PDF et 23 fiches) | `python -m incident_assistant.indexing` |
| Recherche hybride (sémantique et BM25, fusion RRF) avec contrôle des preuves | `incident_assistant/retrieval.py` |
| Reranking optionnel par cross-encoder | `RERANK_PASSAGES=true`, `python -m evaluation.compare_reranking` |
| Feedback utilisateur (👍 / 👎, diagnostic, sources, commentaire, correction) | interface Web, `python -m incident_assistant.feedback` |
| Dashboard : usage, feedback, résultats des benchmarks, analyse des incidents | page *Dashboard* de l'interface ([app/pages/1_Dashboard.py](app/pages/1_Dashboard.py)) |
| Validation automatique de la base documentaire | `python scripts/validate_knowledge_base.py` ([knowledge_base/README.md](knowledge_base/README.md)) |
| Évaluation de la recherche et de la génération, fine-tuning des embeddings | `evaluation/`, `finetuning/` (voir plus bas) |
| Conteneurs : interface, Qdrant et indexation | [docker-compose.yml](docker-compose.yml) |
| Intégration continue : syntaxe, secrets, tests, image Docker | [.github/workflows/ci.yml](.github/workflows/ci.yml) |

## Architecture en bref

```
Incident ──> Agent d'analyse (LLM) ──> requêtes ──> Recherche hybride ──> Preuves suffisantes ?
                 │                                   (sémantique + BM25,      (score cross-encoder) │ non (max 2 fois)
                 │ description trop vague            fusion RRF)                                   └──> Reformulation ──┐
                 v                                         ^────────────────────────────────────────────────────────────┘
          Questions de précision                           │ oui
                                                  Agent d'investigation (LLM) ──> Validation des citations ──> Réponse
```

- **LangChain** fournit les briques : chargement et découpage des documents, embeddings, Qdrant, ChatGroq, prompts et sorties structurées Pydantic, outils.
- **LangGraph** orchestre le workflow ([incident_assistant/workflow.py](incident_assistant/workflow.py)) : branchements, boucle de reformulation bornée, état partagé.
- **MCP** : un serveur ([incident_assistant/mcp_server.py](incident_assistant/mcp_server.py)) expose `search_knowledge_base` et `get_document_metadata`.

## Configuration finale

Le système livré est unique. Le workflow fonctionne ainsi :

| Étape | Configuration |
|---|---|
| Requêtes | requêtes de l'agent d'analyse et messages d'erreur exacts, 5 au plus |
| Recherche | hybride : sémantique et BM25, 20 candidats par recherche, fusion RRF (k = 60), 6 passages conservés dans l'ordre RRF (par défaut ; voir l'option de reranking) |
| Contrôle des preuves | cross-encoder, sans changement d'ordre : au moins 3 passages avec un score ≥ -2,86 |
| Reformulation | 2 fois au plus, puis statut `insufficient_evidence` si les preuves restent insuffisantes |
| Citations | validées par le code ; une étape ou une solution sans passage qui l'énonce est affichée comme non sourcée |

Par défaut, le reclassement par le cross-encoder (stratégie `hybrid_rerank` du benchmark) n'est pas utilisé par le workflow : il peut être activé avec l'option décrite ci-dessous. Les embeddings fine-tunés ne servent qu'aux expérimentations. Le serveur MCP expose la recherche seule, sans agents ni cross-encoder.

**Option de reranking.** Avec `RERANK_PASSAGES=true` dans `.env`, le cross-encoder choisit et ordonne les 6 passages parmi les 20 meilleurs candidats RRF. Chaque passage garde ses métadonnées et son rang RRF d'origine, affiché dans l'onglet Sources. L'option est désactivée par défaut, pour que le système final reste celui des résultats enregistrés.

Sur le benchmark :

- avec les requêtes de l'agent d'analyse, le MRR passe de 0,941 à 0,965, pour environ 2,5 s de plus par requête ;
- avec les requêtes brutes, il baisse de 0,990 à 0,951.

Pour un benchmark de génération avec l'option activée, utilisez un tag distinct. `python -m evaluation.compare_reranking "<incident>"` compare les passages avant et après le reranking pour une question.

**Interactions et feedback.** Chaque réponse est enregistrée dans une base SQLite locale, `storage/assistant.db` (non versionnée ; SQLite fait partie de Python, sans serveur ni dépendance). Le code est dans [incident_assistant/feedback.py](incident_assistant/feedback.py), avec deux tables :

- `interactions`, remplie automatiquement : question, date, session, statut, technologies détectées, causes et solutions proposées, documents cités et documents des passages, nombre de reformulations, temps de réponse, configuration RAG (modèles, collection, reranking, règle de preuves) ;
- `feedback`, une ligne au plus par réponse : 👍 / 👎, diagnostic correct / partiellement correct / incorrect, pertinence des sources, solution qui n'a pas fonctionné, correction proposée, commentaire. Une nouvelle évaluation de la même réponse remplace la précédente.

Le texte des passages, la trace et la clé API ne sont jamais enregistrés.

**Dashboard.** La page *Dashboard* (barre latérale de l'interface) ne montre que des données réelles, avec des filtres par période et par technologie :

| Section | Source des données |
|---|---|
| A. Usage : questions, sessions, diagnostics, temps moyen, questions par jour, statuts | table `interactions` |
| B. Qualité : part de 👍 / 👎, diagnostic, pertinence des sources, satisfaction dans le temps, tableau des réponses mal évaluées | table `feedback` |
| C. Performance : Recall@k, MRR, rappel au niveau des preuves, impact du reranking, qualité de génération (juge LLM) | fichiers de résultats des benchmarks (`evaluation/results/*.json`) |
| D. Incidents : technologies concernées, documents les plus cités, causes et solutions les plus proposées | table `interactions` |

Sans données, chaque section l'indique au lieu d'afficher des valeurs fictives. Les graphiques sont ceux de Streamlit, construits sur Altair, déjà installé avec Streamlit : Plotly n'apporterait rien d'indispensable ici et ajouterait une dépendance.

**Cycle d'amélioration.**

1. L'assistant répond, et l'interaction est enregistrée.
2. L'utilisateur évalue la réponse.
3. Le dashboard repère les réponses mal jugées, les sources peu pertinentes et l'évolution de la satisfaction.
4. `python -m incident_assistant.feedback --export-candidates candidats.jsonl` exporte les réponses évaluées qui pourraient enrichir le jeu d'évaluation :
   - `confirmed` : diagnostic correct et sources pertinentes, donc une paire candidate (question, documents attendus) ;
   - `to_fix` : réponse jugée mauvaise, avec la correction proposée.
5. Chaque candidat porte `review_status: to_review`. Il n'est ajouté à un benchmark, ou utilisé pour entraîner les embeddings, qu'après vérification manuelle.
6. Le benchmark rejoué dit si un changement du retrieval, du reranking ou des embeddings améliore réellement les résultats.

Aucun fine-tuning n'est lancé automatiquement à partir du feedback.

## Structure du projet

```
incident_assistant/      code de l'application
  config.py              paramètres (surchargeables dans .env)
  documents.py           chargement PDF/Markdown, nettoyage, chunking, métadonnées
  indexing.py            collection Qdrant (dense + BM25), indexation incrémentale
  retrieval.py           recherche sémantique, BM25, fusion RRF, score cross-encoder, contrôle des preuves
  agents.py              agent d'analyse, agent d'investigation, reformulation
  workflow.py            graphe LangGraph et validation des citations
  feedback.py            base SQLite des interactions et du feedback, statistiques, candidats d'évaluation
  mcp_server.py          serveur MCP (stdio)
app/streamlit_app.py     interface Web (question, réponse sourcée, feedback)
app/pages/1_Dashboard.py dashboard (usage, feedback, benchmarks, incidents)
scripts/                 ask.py (ligne de commande), démos client MCP et agent MCP, validate_knowledge_base.py
knowledge_base/          manifest.yaml (PDF retenus / exclus), markdown/ (23 fiches), pdf/ (non versionné), README.md
evaluation/              datasets/ (63 incidents), métriques, benchmarks, compare_reranking.py, results/
finetuning/              génération des paires, entraînement, data/ (paires), results/ (journal d'entraînement)
tests/                   tests unitaires et d'intégration (pytest)
docs/                    cahier des charges, rapport technique, scénarios de démonstration
Dockerfile, docker-compose.yml, .dockerignore    conteneurs
.github/workflows/ci.yml                         intégration continue
```

Documents : [rapport technique](docs/rapport_technique_final.docx) · [cahier des charges](docs/cahier_des_charges_final.docx) · [scénarios de démonstration](docs/demo_scenarios.md) · [résultats du benchmark](evaluation/results/README.md).

## Installation

Prérequis : Python 3.11 ou plus récent, et une clé API Groq gratuite (https://console.groq.com).

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS : source .venv/bin/activate)
pip install -r requirements.txt
pip install -e .                  # rend le paquet incident_assistant importable partout
copy .env.example .env            # puis mettre votre GROQ_API_KEY dans .env
```

Les PDF ne sont pas dans le dépôt, pour des raisons de licence. Placez les 6 PDF retenus aux chemins indiqués dans [knowledge_base/manifest.yaml](knowledge_base/manifest.yaml) (`included: true`). Le champ `official_url` indique où les obtenir quand une source officielle existe. Sans les PDF, retirez-les du manifeste (`included: false`) : l'assistant fonctionne alors avec les 23 fiches.

## Lancement

```bash
# 1. Indexer la base (première fois : ~5 min sur CPU ; ensuite seuls les fichiers modifiés sont traités)
python -m incident_assistant.indexing
python -m incident_assistant.indexing --rebuild      # tout réindexer

# 2. Interface Web (le Dashboard est une page de la barre latérale)
streamlit run app/streamlit_app.py
python -m incident_assistant.feedback                # statistiques d'usage et de feedback en ligne de commande

# 3. Ligne de commande
python scripts/ask.py "After deploying version 2.4 our pods restart and kubectl shows CrashLoopBackOff"

# 4. MCP : client de démonstration, puis agent qui utilise les outils par Tool Calling
python scripts/mcp_client_demo.py
python scripts/mcp_agent_demo.py "How do I release a stale Terraform state lock?"
#    ou avec l'inspecteur officiel : npx @modelcontextprotocol/inspector python -m incident_assistant.mcp_server
```

**Important** : par défaut, Qdrant fonctionne en mode embarqué (`storage/qdrant`). Ce mode n'accepte **qu'un seul processus à la fois**. Fermez Streamlit avant de lancer le serveur MCP, les tests ou un benchmark. Pour plusieurs processus simultanés, lancez Qdrant en serveur (`docker compose up -d qdrant`), mettez `QDRANT_URL=http://localhost:6333` dans `.env` et réindexez.

**Docker** : l'interface et Qdrant peuvent aussi tourner entièrement en conteneurs. La procédure complète est en tête de [docker-compose.yml](docker-compose.yml) :

```bash
docker compose build
docker compose --profile init run --rm indexer     # indexation initiale (~15 min sur CPU avec les PDF)
docker compose up -d                               # http://localhost:8501
```

La clé Groq est lue dans `.env` au démarrage ; elle n'est jamais copiée dans l'image. Le feedback et le registre d'indexation sont conservés dans des volumes Docker.

## Tests

```bash
pytest -m "not integration"     # tests unitaires : rapides, sans index ni LLM
pytest -m integration           # index réel, serveur MCP via un vrai client, workflow complet avec le LLM
```

La suite compte 275 tests : 266 tests sans index ni LLM et 9 tests d'intégration. Les tests utilisent une base d'interactions temporaire (`tests/conftest.py`) : ils n'écrivent jamais dans `storage/assistant.db`. Sans ces éléments, les tests d'intégration sont ignorés ; c'est le cas de la CI GitHub Actions, qui désélectionne aussi les 2 tests lisant les PDF, non versionnés.

```bash
python scripts/validate_knowledge_base.py      # contrôle de la base documentaire (voir knowledge_base/README.md)
```

## Évaluation et fine-tuning

```bash
python -m evaluation.run_retrieval_benchmark        # BM25 / sémantique / hybride / hybride + reranker
python -m evaluation.tune_evidence                  # seuil de preuves choisi sur un jeu de validation distinct du test
python -m evaluation.run_generation_benchmark --tag v2 --answers-only   # système final : réponses seules
python -m evaluation.run_generation_benchmark --tag v2                  # système final : jugements (reprenable)
python -m evaluation.abstention --tag v2            # abstention, calculée sans LLM sur les réponses en cache
python -m evaluation.run_generation_benchmark       # configuration antérieure comparée (résultats en cache)
python -m finetuning.generate_pairs                 # paires (question, passage) générées par LLM
python -m finetuning.train_embeddings               # fine-tuning de all-MiniLM-L6-v2 (CPU)
python -m incident_assistant.indexing --collection devops_kb_ft --model finetuning/output/minilm-devops
python -m evaluation.run_retrieval_benchmark --raw-only --collection devops_kb_ft \
       --model finetuning/output/minilm-devops --strategies semantic hybrid --tag finetuned
python -m evaluation.make_report                    # tableaux + graphiques dans evaluation/results/

# Benchmark final (37 questions annotées au niveau des passages de preuve)
python -m evaluation.run_retrieval_benchmark --dataset evaluation/datasets/benchmark_v1.json --tag bench_v1 --raw-only
python -m evaluation.run_generation_benchmark --dataset evaluation/datasets/benchmark_v1.json --tag bench_v1
```

**Résultats du benchmark final** (`benchmark_v1`, 34 questions résolubles, requêtes brutes, pertinence au niveau du document et des preuves) :

| Stratégie | Recall@1 | Recall@5 | MRR | Recall@5 des preuves | MRR des preuves | s / requête |
|---|---|---|---|---|---|---|
| BM25 | 0,676 | 0,882 | 0,877 | 0,534 | 0,541 | 0,23 |
| Dense | 0,750 | 0,912 | 0,929 | 0,613 | 0,572 | 0,05 |
| Hybride RRF | 0,721 | 0,912 | 0,909 | 0,627 | 0,605 | 0,37 |
| Hybride + reranking | 0,691 | 0,882 | 0,896 | 0,564 | 0,560 | 3,17 |

Génération sur ce jeu (juge LLM) : correctness 0,882, faithfulness 0,609, answer relevancy 1,000, 24,8 s par question ; les 3 questions hors périmètre sont signalées. L'hybride RRF retrouve le plus de preuves ; le reranking dégrade toutes les mesures pour un temps environ 9 fois plus long, et reste donc désactivé par défaut.

`evaluation/calibrate_evidence.py` est le premier calibrage du seuil, conservé pour la traçabilité. Il a été remplacé par `tune_evidence.py`.

**Identifiants techniques.** `v2` (option `--tag v2`, fichiers `*_v2.json`, dossier `generation_v2/`) désigne les résultats du système final. Les fichiers sans suffixe contiennent ceux de la configuration antérieure, conservés pour l'expérience comparative. Ces noms ne désignent pas deux produits ; ils sont conservés parce que le code de benchmark et les tests en dépendent.

## Modèles utilisés

| Rôle | Modèle | Où |
|---|---|---|
| Agents (analyse, investigation, reformulation) | `openai/gpt-oss-120b` (Groq) | `LLM_MODEL` ; ou un modèle par agent avec `ANALYZER_MODEL` (analyse et reformulation) et `INVESTIGATOR_MODEL`, qui valent `LLM_MODEL` par défaut |
| Juge du benchmark de génération | `qwen/qwen3.8-27b` (Groq), d'une autre famille que les agents | `JUDGE_MODEL` |
| Génération des paires de fine-tuning | `openai/gpt-oss-20b` (Groq) | `PAIR_MODEL` |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local) | `EMBEDDING_MODEL` |
| BM25 | `Qdrant/bm25` (FastEmbed), avec le modificateur IDF de Qdrant | - |
| Score des preuves (cross-encoder) | `cross-encoder/ms-marco-MiniLM-L6-v2` (local) ; par défaut, il sert seulement à juger les preuves, l'ordre des passages restant celui de RRF ; avec `RERANK_PASSAGES=true`, il choisit aussi les passages | `RERANKER_MODEL` |

Le compte Groq gratuit limite chaque modèle à environ 8 000 tokens par minute et 200 000 tokens par jour. Une investigation consomme environ 4 000 tokens. Les benchmarks sont donc reprenables : leurs résultats sont mis en cache dans `evaluation/results/generation_v2/` (système final) et `evaluation/results/generation/` (configuration antérieure).

## Dépannage

- **Le téléchargement des modèles Hugging Face reste bloqué** : définissez `HF_HUB_DISABLE_XET=1`. Une fois les modèles en cache, `HF_HUB_OFFLINE=1` évite les accès réseau.
- **`Storage folder ... is already accessed by another instance`** : un autre processus utilise Qdrant en mode embarqué. Voir la remarque ci-dessus.
- **« The LLM service is temporarily unavailable »** : quota Groq atteint. Une limite par minute est réessayée automatiquement, avec le délai donné par Groq. Pour un quota journalier épuisé, l'assistant s'arrête tout de suite et indique le délai fourni par Groq : relancez après ce délai. Aucune réponse incomplète n'est affichée.
- **Changer de modèle** : les benchmarks enregistrés refusent un autre modèle que celui qui a produit leurs résultats. Pour évaluer un autre modèle, utilisez un tag distinct, par exemple `--tag essai-20b`.
