# Benchmark OCR : Évaluation et Recommandations (Service P6 & Ingestion P1)

> **Date** : 24 Novembre 2026  
> **Auteur** : Équipe Ingestion (P1)  
> **Contexte** : Choix de la configuration Tesseract OCR pour le service souverain P6 et la chaîne d'ingestion documentaire du Bulletin Officiel du Royaume du Maroc (SGG).  
> **Statut** : Validé pour intégration (Règle B satisfaite à 100 %).

---

## 1. Synthèse Exécutive & Recommandations

Ce benchmark a évalué l'exactitude textuelle, la fidélité des nombres et les performances CPU de Tesseract OCR sur des pages scannées du Bulletin Officiel marocain (`sgg_7433.pdf`), comparées à une vérité terrain vérifiée manuellement.

### Décisions clés pour le service P6 et l'Ingestion P1

| Composant | Paramètre recommandé | Justification |
| :--- | :--- | :--- |
| **Moteur OCR** | **Tesseract 5.x** (LSTM / OEM 1) | Moteur souverain, hors ligne, léger et rapide sur CPU. |
| **Modèle linguistique** | **`tessdata_best` (`ara`)** | Atteint **F1 = 0,877** contre 0,843 pour `default` ; réduit drastiquement les confusions de glyphes. |
| **Mode de segmentation (PSM)** | **`--psm 3`** (Fully automatic page segmentation) | Préserve l'intégrité de la page. `psm 6` échoue à segmenter les blocs complexes. |
| **Prétraitement d'image** | **Aucun** (image brute issue du rendu PDF) | Les filtres de contraste automatique et suppression de lignes dégradent le F1 de 1 à 18 points. |
| **Résolution de rendu (P1)** | **DPI adaptatif** :<br>• $\le 150\text{ DPI}$ natif $\rightarrow$ Rendu à **200 DPI**<br>• $\approx 300\text{ DPI}$ natif $\rightarrow$ Rendu à **300 DPI** | Évite le flou d'interpolation qui dégrade la lecture des points arabes sur les scans basse résolution. |

### Validation des critères contractuels

- **Règle Initiale** ($F1 \ge 0,85$ ET Rappel global des nombres $\ge 0,90$) : **Non atteinte** (rappel global à 61,6 %), en raison de la présence d'une grille de tableau budgétaire dense de 104 nombres que Tesseract ne peut structurer.
- **Règle B (Texte juridique)** ($F1 \ge 0,85$ ET Rappel nombres texte $\ge 0,90$) : **VALIDÉE avec succès** :
  - **F1 Mots** : **0,877** ($\ge 0,85$)
  - **CER (Taux d'erreur caractères)** : **0,226**
  - **Rappel des nombres dans le texte** : **100,0 %** (34/34 nombres identifiés)
  - **Temps moyen par page** : **5,26 s** sur CPU (soit ~4,7 minutes pour un BO complet de 54 pages scannées).

---

## 2. Jeu de Test & Cadre Méthodologique

### Jeu de données (Vérité Terrain)
- **Document source** : `data/raw/public/sgg_7433.pdf` (Édition générale n° 7433).
- **Pages sélectionnées** : Pages 8, 9, 10 et 11 (Folios 6760 à 6763).
- **Vérité terrain** : Transcriptions manuelles strictes stockées dans `cache/transcriptions_sgg_7433_pages_8_11/`.
- **Répartition des nombres (138 au total)** :
  - **Classe "Texte" (34 nombres)** : Numéros de dahirs, décrets, articles, dates d'application et folios.
  - **Classe "Tableau" (104 nombres)** : Lignes comptables et montants budgétaires avec séparateurs de milliers et décimales (Article 3, page 9).

### Métriques d'évaluation
1. **F1 Mots** : Moyenne harmonique de la précision et du rappel des mots arabes normalisés (`normalize_ar`).
2. **CER (Character Error Rate)** : Distance de Levenshtein au niveau caractère rapportée à la longueur de la vérité terrain.
3. **Rappel des nombres (Critère b - Chiffres seuls)** : Vérifie si la séquence ordonnée des chiffres du nombre apparaît dans le texte extrait, en faisant abstraction des séparateurs (espaces, points, virgules).
4. **Nombres erronés ("inventés")** : Nombre de séquences numériques présentes dans l'OCR mais absentes de la vérité terrain.
5. **Temps CPU** : Temps d'exécution par page sur processeur standard (x86_64).

---

## 3. Audit de Résolution du Corpus (Partie A)

L'audit exhaustif des 28 fichiers PDF du corpus (`data/raw/public/` et `corpus_archive`) a mis en évidence une distribution **bimodale** des scans :

| Fichier | Pages scannées / Total | Dimensions natives (px) | DPI Min | DPI Médiane | DPI Max | Type de document |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `sgg_7433.pdf` | 54 / 66 | $870 \times 1231$ | 99,1 | **106,3** | 121,4 | Scan basse résolution |
| `sgg_7415-bis.pdf` | 195 / 198 | $881 \times 1247$ | 101,7 | **106,6** | 119,9 | Scan basse résolution |
| `sgg_7543-bis.pdf` | 508 / 511 | $1240 \times 1530$ | 138,1 | **140,3** | 141,5 | Scan résolution moyenne |
| `sgg_7429-bis.pdf` | 373 / 376 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7512-bis.pdf` | 142 / 145 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7519.pdf` | 69 / 90 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7434.pdf` | 61 / 87 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7521.pdf` | 55 / 89 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7403.pdf` | 51 / 84 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7387.pdf` | 46 / 77 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `sgg_7418.pdf` | 48 / 89 | $2481 \times 3510$ | 300,1 | **300,1** | 300,1 | Scan haute résolution |
| `adala_001.pdf` à `008` | 1 / N | $1653 \times 2339$ | 200,0 | **200,0** | 200,0 | Page de garde scannée |
| 14 autres PDF | 0 (100% natifs) | - | - | - | - | Documents numériques |

> [!IMPORTANT]
> **Conclusion sur les résolutions** :  
> Tous les scans ne sont pas à ~115 DPI. Plus de 850 pages du corpus sont en réalité à **300 DPI natif**.  
> En conséquence, l'ingestion doit impérativement inspecter la résolution native de l'image embarquée avant rendu pour adapter le DPI cible (200 DPI pour les scans anciens $\le 150\text{ DPI}$ ; 300 DPI pour les scans récents à 300 DPI).

---

## 4. Analyse Diagnostique : Pourquoi les résultats initiaux semblaient "mauvais"

Le premier tour d'évaluation affichait un rappel faible (~45 %) et près de 90 faux positifs numériques. Le diagnostic a révélé trois facteurs explicatifs :

### A. Artefact de la métrique stricte (Égalité exacte)
Les montants budgétaires comportent jusqu'à 14 chiffres (ex. `181.580.601.851,55`). Si Tesseract insère une espace après un point (`181. 580...`) :
1. Le montant réel est déclaré "non reconnu" (rappel nul).
2. Les deux fragments (`181` et `580...`) sont comptabilisés comme deux nombres "inventés".
Le passage au **critère (b)** (recherche de la suite continue de chiffres) rétablit la réalité de la lecture.

### B. Sur-échantillonnage et flou d'interpolation
Effectuer un rendu à 300 ou 400 DPI sur un scan source de 106 DPI agrandit artificiellement les défauts de numérisation. Les points arabes (qui distinguent par exemple ب, ت, ث, ن) bavent et se fondent dans les lettres. Réduire le rendu à **200 DPI** a immédiatement augmenté le F1 de 4,5 points et diminué le temps de calcul de 53 %.

### C. Structure tabulaire vs Texte continu
Tesseract lit de droite à gauche en suivant les lignes de base textuelles. Devant une grille de tableau financier sans modèle de segmentation tabulaire, les séparateurs verticaux sont parfois lus comme des chiffres `1` et les colonnes adjacentes se mélangent.

---

## 5. Résultats Détaillés du Benchmark (Tour 2)

Sur 30 configurations explorées en deux étapes (modèles `default` vs `best`, PSM 3 vs 6, résolutions 150, 180, 200 DPI, et prétraitements), voici le classement des configurations représentatives :

| Rang | Configuration | Modèle | PSM | DPI | F1 Mots | CER | Rappel Texte (b) | Rappel Tableau (b) | Rappel Global (b) | Faux nbrs | Temps moy / page | Règle B |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | `best_psm3_none_200dpi` | `best` | **3** | **200** | **0,877** | **0,226** | **100,0 %** | **49,0 %** | **61,6 %** | **25** | **5,26 s** | **VALIDÉ** |
| 2 | `best_psm3_ara_eng_200dpi` | `best` | 3 | 200 | 0,877 | 0,226 | 100,0 % | 49,0 % | 61,6 % | 25 | 5,66 s | **VALIDÉ** |
| 3 | `best_psm3_none_150dpi` | `best` | 3 | 150 | 0,873 | 0,229 | 100,0 % | 43,3 % | 57,2 % | 16 | 4,58 s | **VALIDÉ** |
| 4 | `best_psm6_none_200dpi` | `best` | 6 | 200 | 0,867 | 0,232 | 97,1 % | 38,5 % | 52,9 % | 20 | 5,52 s | **VALIDÉ** |
| 5 | `best_psm6_none_180dpi` | `best` | 6 | 180 | 0,867 | 0,234 | 100,0 % | 47,1 % | 60,1 % | 18 | 6,05 s | **VALIDÉ** |
| 6 | `best_psm3_autocontrast_200dpi`| `best`| 3 | 200 | 0,866 | 0,237 | 100,0 % | 46,2 % | 59,4 % | 23 | 4,91 s | **VALIDÉ** |
| 7 | `default_psm6_none_200dpi` | `default` | 6 | 200 | 0,843 | 0,224 | 97,1 % | 31,7 % | 47,8 % | 34 | 2,05 s | Échec ($F1 < 0,85$) |
| 8 | `default_psm3_none_200dpi` | `default` | 3 | 200 | 0,839 | 0,236 | 100,0 % | 34,6 % | 50,7 % | 36 | 2,28 s | Échec ($F1 < 0,85$) |
| 9 | `best_psm3_removelines_200dpi` | `best` | 3 | 200 | 0,774 | 0,238 | 97,1 % | 51,0 % | 62,3 % | 37 | 6,12 s | Échec |
| 10 | `best_psm3_preserve_spaces_200dpi`| `best`| 3 | 200 | 0,789 | 0,235 | 100,0 % | 49,0 % | 61,6 % | 28 | 7,53 s | Échec |

---

## 6. Expérience sur les Cellules de Tableau Découpées (Partie D)

Une expérience ciblée a testé l'extraction des cellules individuelles de tableau découpées par morphologie mathématique (sur les pages 9 et 10) avec passage en `--psm 7` (Single text line) et whitelist de chiffres :
- **Rappel obtenu** : **0,0 %**.
- **Temps moyen par page** : **15,65 s** (soit le triple du temps standard).
- **Raison de l'échec** : Le découpage automatique des cellules coupe arbitrairement les séparateurs décimaux et les bordures de cellule créent des artefacts bruités que la whitelist de chiffres transforme en faux nombres.

> [!NOTE]
> Cette tentative confirme qu'un pipeline heuristique de découpage de cellules n'est pas viable. L'extraction fiable de tableaux denses scannés nécessite un modèle de document vision (Table Transformer, LayoutLM) et ne doit pas retarder le déploiement du service OCR textuel.

---

## 7. Spécifications pour l'Intégration P6 & Ingestion P1

### A. Déploiement du Service OCR (`services/ocr/`)
1. **Fichier Dockerfile** :
   - Conserver l'image Debian Bookworm avec les paquets officiels `tesseract-ocr` et `libtesseract-dev`.
   - Télécharger et placer le modèle optimisé dans `/usr/share/tesseract-ocr/5/tessdata/ara.traineddata` depuis le dépôt officiel [tessdata_best](https://github.com/tesseract-ocr/tessdata_best).
2. **Configuration Tesseract dans `app.py`** :
   ```python
   # Configuration validée par le benchmark
   TESSERACT_CONFIG = "--oem 1 --psm 3"
   TESSERACT_LANG = "ara"  # ou "ara+fra" si du français est attendu
   ```
3. **Calcul de confiance** :
   - Maintenir le calcul ignorant les tokens `conf == -1` (séparateurs et sauts de ligne).
   - Confiance ramenée sur une échelle $0,0$ à $1,0$.

### B. Adaptation du Module d'Ingestion (`src/ingestion/extract.py`)
Intégrer la logique de résolution adaptative avant l'appel OCR :
```python
def get_optimal_render_dpi(page: fitz.Page) -> int:
    """Détermine le DPI optimal selon la résolution native du scan."""
    images = page.get_image_info(xrefs=True)
    if not images:
        return 300  # Page vectorielle ou sans image détectée

    largest = max(images, key=lambda x: x["width"] * x["height"])
    rect = page.rect
    native_dpi = largest["width"] / (rect.width / 72.0)

    # Si le scan d'origine est en basse résolution, éviter l'upsampling flou
    if native_dpi <= 150:
        return 200
    return 300
```

---

## 8. Reproductibilité du Benchmark

Le benchmark a été exécuté à l'aide d'un harnais d'évaluation local (`scripts/ocr_benchmark.py`, maintenu localement conformément au protocole de test pour préserver le périmètre de coordination du dossier `/scripts/`).

Pour reproduire les mesures en local :
```bash
# Exécution avec l'environnement dédié OCR et Tesseract 5.x
python scripts/ocr_benchmark.py
```

L'ensemble des résultats bruts et artefacts d'évaluation est consigné dans le cache d'ingestion :
- **Métriques structurées** : `cache/ocr_bench/round2/results.json`
- **Synthèse d'évaluation** : `cache/ocr_bench/round2/results.md`
- **Extractions OCR brutes** : `cache/ocr_bench/round2/ocr_texts/`
- **Visualiseur HTML de diagnostic** : `cache/ocr_bench/diag/numbers_page_09.html`
- **Vérité terrain de référence** : `cache/transcriptions_sgg_7433_pages_8_11/`

