# DevOps Incident Investigation Assistant

Projet de la matière **Programmation Python Data Science avancée**. L'assistant aide à investiguer un incident DevOps / Cloud décrit en langage naturel. Il :

- analyse l'incident ;
- recherche dans une base documentaire, en combinant recherche sémantique et BM25 ;
- propose des causes possibles, des étapes de diagnostic et des solutions, **chacune reliée à ses sources** (document + page ou section) ;
- signale clairement quand la documentation ne suffit pas.

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
| Recherche | hybride : sémantique et BM25, 20 candidats par recherche, fusion RRF (k = 60), 6 passages conservés dans l'ordre RRF |
| Contrôle des preuves | cross-encoder, sans changement d'ordre : au moins 3 passages avec un score ≥ -2,86 |
| Reformulation | 2 fois au plus, puis statut `insufficient_evidence` si les preuves restent insuffisantes |
| Citations | validées par le code ; une étape ou une solution sans passage qui l'énonce est affichée comme non sourcée |

Le reclassement par le cross-encoder (stratégie `hybrid_rerank`) et les embeddings fine-tunés ne servent qu'aux expérimentations : ni le workflow ni le serveur MCP ne les utilisent. Le serveur MCP expose la recherche seule, sans agents ni cross-encoder.

## Structure du projet

```
incident_assistant/      code de l'application
  config.py              paramètres (surchargeables dans .env)
  documents.py           chargement PDF/Markdown, nettoyage, chunking, métadonnées
  indexing.py            collection Qdrant (dense + BM25), indexation incrémentale
  retrieval.py           recherche sémantique, BM25, fusion RRF, score cross-encoder, contrôle des preuves
  agents.py              agent d'analyse, agent d'investigation, reformulation
  workflow.py            graphe LangGraph et validation des citations
  mcp_server.py          serveur MCP (stdio)
app/streamlit_app.py     interface Web
scripts/                 ask.py (ligne de commande), démos client MCP et agent MCP
knowledge_base/          manifest.yaml (PDF retenus / exclus), markdown/ (23 fiches), pdf/ (non versionné)
evaluation/              jeu d'évaluation (63 incidents), métriques, benchmarks, résultats
finetuning/              génération des paires, entraînement, résultats
tests/                   tests unitaires et d'intégration (pytest)
docs/                    cahier des charges, rapport technique
```

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

# 2. Interface Web
streamlit run app/streamlit_app.py

# 3. Ligne de commande
python scripts/ask.py "After deploying version 2.4 our pods restart and kubectl shows CrashLoopBackOff"

# 4. MCP : client de démonstration, puis agent qui utilise les outils par Tool Calling
python scripts/mcp_client_demo.py
python scripts/mcp_agent_demo.py "How do I release a stale Terraform state lock?"
#    ou avec l'inspecteur officiel : npx @modelcontextprotocol/inspector python -m incident_assistant.mcp_server
```

**Important** : par défaut, Qdrant fonctionne en mode embarqué (`storage/qdrant`). Ce mode n'accepte **qu'un seul processus à la fois**. Fermez Streamlit avant de lancer le serveur MCP, les tests ou un benchmark. Pour plusieurs processus simultanés, lancez Qdrant en serveur (`docker compose up -d`), mettez `QDRANT_URL=http://localhost:6333` dans `.env` et réindexez.

## Tests

```bash
pytest -m "not integration"     # tests unitaires : rapides, sans index ni LLM
pytest -m integration           # index réel, serveur MCP via un vrai client, workflow complet avec le LLM
```

La suite compte 101 tests : 92 tests sans index ni LLM et 9 tests d'intégration.

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
python -m evaluation.review_agreement --prepare     # relecture humaine (voir docs/relecture_humaine.md)
```

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
| Score des preuves (cross-encoder) | `cross-encoder/ms-marco-MiniLM-L6-v2` (local) ; il sert seulement à juger les preuves, l'ordre des passages restant celui de RRF | `RERANKER_MODEL` |

Le compte Groq gratuit limite chaque modèle à environ 8 000 tokens par minute et 200 000 tokens par jour. Une investigation consomme environ 4 000 tokens. Les benchmarks sont donc reprenables : leurs résultats sont mis en cache dans `evaluation/results/generation_v2/` (système final) et `evaluation/results/generation/` (configuration antérieure).

## Dépannage

- **Le téléchargement des modèles Hugging Face reste bloqué** : définissez `HF_HUB_DISABLE_XET=1`. Une fois les modèles en cache, `HF_HUB_OFFLINE=1` évite les accès réseau.
- **`Storage folder ... is already accessed by another instance`** : un autre processus utilise Qdrant en mode embarqué. Voir la remarque ci-dessus.
- **« The LLM service is temporarily unavailable »** : quota Groq atteint. Une limite par minute est réessayée automatiquement, avec le délai donné par Groq. Pour un quota journalier épuisé, l'assistant s'arrête tout de suite et indique le délai fourni par Groq : relancez après ce délai. Aucune réponse incomplète n'est affichée.
- **Changer de modèle** : les benchmarks enregistrés refusent un autre modèle que celui qui a produit leurs résultats. Pour évaluer un autre modèle, utilisez un tag distinct, par exemple `--tag essai-20b`.
