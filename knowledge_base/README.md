# Base documentaire

Ce dossier contient tout ce que l'assistant peut indexer et citer. Le validateur [`scripts/validate_knowledge_base.py`](../scripts/validate_knowledge_base.py) contrôle automatiquement les règles décrites ici.

## Organisation

```
knowledge_base/
  manifest.yaml        décisions sur le corpus PDF : 105 fichiers décrits, 6 indexés
  markdown/<domaine>/  23 fiches de diagnostic rédigées par l'équipe (toutes indexées)
  pdf/<domaine>/       les PDF eux-mêmes : jamais versionnés dans Git (licences)
  README.md            ce fichier (non indexé)
```

Deux types de sources coexistent :

- **Les PDF** sont décrits dans `manifest.yaml`. Seuls ceux marqués `included: true` sont indexés.
- **Les fiches Markdown** se décrivent elles-mêmes par leur front matter YAML. Elles ne figurent **pas** dans le manifeste : tout fichier `.md` placé sous `markdown/` est indexé.

Un fichier `.md` placé hors de `markdown/`, ou un PDF absent du manifeste, n'est jamais indexé : le validateur le signale.

## Format du manifeste

```yaml
summary:                  # totaux recalculés et comparés par le validateur
  total_files: 105
  included_files: 6
  included_pages: 1273
  excluded_files: 99
reference_sources:        # sources citées mais jamais indexées (ex. Google SRE Book)
- doc_id: web-google-sre-book
  ...
documents:
- doc_id: pdf-progit                    # unique, préfixe pdf-
  path: pdf/git/progit.pdf              # relatif à knowledge_base/, unique
  title: Pro Git
  pages: 501
  sha256: <empreinte du fichier>        # vérifiée pour les PDF indexés
  included: true                        # true = indexé
  license: ...                          # traçabilité attendue pour un PDF indexé
  provenance: open_license
  official_url: https://...             # ou null, avec url_check qui explique pourquoi
  url_check: ...
- doc_id: pdf-ansible-best-practices
  included: false
  exclusion_reasons: [...]              # attendu pour un PDF exclu
  reintegrable: false
```

Champs obligatoires de chaque entrée : `doc_id`, `path`, `title` et `included` (booléen).

## Format d'une fiche Markdown

Une fiche commence par un front matter YAML délimité par deux lignes `---`, puis contient un titre `#` et les **11 sections `##` suivantes, dans cet ordre** :

Overview, Symptoms, Possible Causes, Investigation Steps, Diagnostic Commands, Interpretation of Results, Possible Solutions, Prevention, Related Concepts, References, Metadata.

Les sections References et Metadata ne sont pas indexées : elles servent à la traçabilité.

### Métadonnées obligatoires

| Champ | Contenu |
|---|---|
| `doc_id` | identifiant unique, préfixe `md-`. Il peut différer du nom du fichier : ne jamais renommer un `doc_id` existant, car l'évaluation et l'index en dépendent |
| `title` | titre, repris à l'identique dans le `#` du corps |
| `domain` | domaine ; il doit correspondre au dossier (`markdown/<domain>/`) |
| `technology` | liste de technologies |
| `category`, `document_type`, `difficulty` | classification |
| `keywords` | liste de mots-clés |
| `source_type` | toujours `team_written_from_official_docs` |
| `references` | liste de sources `{id: R1, title, publisher, url, accessed}` ; `url` en `https://`, `accessed` obligatoire |

Métadonnées recommandées : `language`, `error_messages`, `last_reviewed` et `review_status`. Le champ facultatif `related_corpus_documents` liste des PDF **indexés** du manifeste (`{doc_id, pages}`).

### Règles de rédaction

- **Citations.** Chaque affirmation tirée d'une source est suivie de sa référence, par exemple `[R1]` ou `[R1, R3]`. Toute référence déclarée doit être citée avant la section References, et toute citation doit être déclarée. La section References liste chaque `[Rn]`.
- **Messages d'erreur.** Un message n'est ajouté que s'il est confirmé par une documentation officielle ou par une observation réelle de l'équipe, signalée comme telle. Les champs `keywords` et `error_messages` du front matter ne sont pas indexés : un message important doit aussi apparaître dans le corps.
- **Raisonnement de l'équipe.** Ce qui vient de l'équipe est marqué « team observation », « team inference » ou « team recommendation ».
- **Liens entre fiches.** On écrit le `doc_id` entre accents graves, par exemple `` `md-terraform-init-errors` ``. Le validateur vérifie que la cible existe.
- **Secrets.** Ne jamais proposer de commande qui affiche la valeur d'un secret.
- **Contenu.** Les blocs de code sont fermés, aucune section n'est vide, et une fiche compte au moins 300 mots (les fiches actuelles en comptent environ 1 100 à 2 300).

## Exécuter le validateur

Depuis la racine du projet :

```bash
python scripts/validate_knowledge_base.py                       # contrôle complet (PDF présents)
python scripts/validate_knowledge_base.py --allow-missing-pdfs  # clone neuf : les PDF ne sont pas dans Git
python scripts/validate_knowledge_base.py --all-hashes          # vérifie aussi l'empreinte des 99 PDF exclus (~10 s)
python scripts/validate_knowledge_base.py --kb-dir <dossier>    # autre dossier
pytest tests/test_validate_knowledge_base.py                    # tests du validateur
```

Le validateur ne fait que lire : il ne modifie aucun fichier, n'écrit aucun rapport et ne touche pas à l'index Qdrant. Il n'a besoin que de PyYAML, déjà présent dans `requirements.txt`.

## Interpréter le rapport

Le rapport liste d'abord les erreurs, puis les avertissements, chacun avec son emplacement (fichier, ou `manifest.yaml: <doc_id>`). Il se termine par un résumé :

```
Summary
  Documents analysed : 128 (23 Markdown guides, 105 manifest entries)
  Valid documents    : 128          documents sans aucune erreur
  Errors             : 0
  Warnings           : 1

Result: PASSED
```

- **Erreur** (code de sortie 1). La base ne doit pas être indexée en l'état :
  - manifeste illisible ;
  - PDF indexé absent ou modifié (empreinte différente) ;
  - identifiant ou chemin en double ;
  - métadonnée obligatoire manquante ;
  - fiche vide ou sans front matter ;
  - section manquante ou dans le désordre ;
  - bloc de code non fermé ;
  - référence non citée, ou citation non déclarée ;
  - lien vers une fiche inexistante ;
  - `related_corpus_documents` pointant vers un PDF inconnu ou exclu.
- **Avertissement** (code de sortie 0). C'est un point à examiner, qui ne bloque pas :
  - métadonnée recommandée absente ;
  - fiche courte ou section vide ;
  - titre `#` différent de `title` ;
  - dossier différent du `domain` ;
  - fiche vers laquelle aucune autre fiche ne renvoie ;
  - totaux de `summary` incohérents ;
  - PDF exclu absent ;
  - fichier présent mais jamais indexé.

Après la correction d'une fiche, relancez le validateur, puis la mise à jour incrémentale de l'index (`python -m incident_assistant.indexing`). Les `chunk_id` de la fiche modifiée changent : les résultats d'évaluation déjà enregistrés portent sur l'ancienne version.
