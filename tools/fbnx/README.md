# fbnx : rétro-ingénierie des données Frostbite de FC 27 sur Switch

But : modifier les données graphiques d'EA SPORTS FC 27 (visages, textures, modèles 3D) pour la version Switch et
les charger dans Eden comme un mod RomFS (LayeredFS).

## Ce qui est établi

D'après le lecteur de Peanuts Native (`dm/gfx/tools/frostbite.py`, testé sur le vrai jeu) :

- RomFS de 31,8 Go : `Data/` (jeu de base) et `Patch/` (mise à jour), `Data/layout.toc`, des tables `.toc` par
  superbundle et des fichiers `cas_NN.cas` par install chunk. `Data/initfs_NX` est chiffré.
- Les manifestes des bundles (liste des ebx, res et chunks) sont stockés **non compressés** dans les `.cas`.
- Les données sont des blocs compressés en **Oodle Leviathan** (codec 0x19), mais le format accepte aussi des blocs
  **non compressés** (codec 0) : on peut réécrire des données modifiées sans compresseur Oodle.
- Textures : ressources `Texture` ; modèles 3D : `MeshSet`.

## Étapes

1. **Tables** (fait avec EdEn.claude › Propriétés du jeu › Extraire des fichiers du jeu, filtre par défaut) :
   `layout.toc`, toutes les `.toc`, `initfs_NX`, `main.npdm`, et `listing.txt` (tous les fichiers du jeu).
   `python3 fbnx.py info <dossier>`.
2. **Manifestes** : `python3 fbnx.py plan-manifests <dossier> --toc <motif>` écrit les lignes à coller dans
   EdEn.claude pour extraire les manifestes des superbundles voulus (personnages, visages), puis
   `python3 fbnx.py manifests <dossier> --grep head` liste leurs ressources.
3. **Ressources** : extraction des textures et des maillages d'un joueur, décodage Oodle (ooz, décodeur libre),
   analyse des formats Switch (textures en block-linear Tegra, maillages).
4. **Écriture** : nouveaux blocs non compressés dans un `cas` ajouté, `.toc` modifiées, le tout dans un mod RomFS
   pour Eden. À vérifier : si le jeu contrôle la signature des `.toc` (sinon, patch de l'ExeFS nécessaire).
5. **Conversion** d'un mod de visage PC vers ces formats.

## Conversion des visages PC (FIFA Editor Tool) → Switch : où on en est (28/11/2026)

| Outil | Rôle |
|---|---|
| `fetm.py` | lit un mod PC `.fifamod` (format « FETM » v3 du FIFA Editor Tool, décodé sur l'AIO FacePack de ViP3eR) : bundles, ebx, res, chunks et leurs données |
| `fbblocks.py` | blocs Frostbite : décodage (Oodle via ooz) et écriture en blocs non compressés |
| `nxtex.py` | textures Tegra X1 : swizzle block-linear (GOB 64 × 8, hauteur de bloc par niveau) |
| `fbtoc.py` | lit et réécrit l'emplacement des éléments d'un bundle dans une `.toc` (réécriture identique vérifiée octet pour octet) |
| `facepack2nx.py` | pack de visages PC → mod RomFS Switch pour Peanuts Native (Mods) ou Eden |

Établi sur le vrai jeu (analyse Peanuts Nova) :

- Les textures de visage Switch ont le **même format de blocs** que sur PC, en **demi-résolution** (512 au lieu de 1024)
  et en block-linear : 512² BC1 sur 10 mips = 177 152 octets, 512² à blocs de 16 octets = 351 744, 256² = 89 600 ;
  ce sont exactement les tailles des chunks de Saka dans le jeu. La conversion ne recompresse rien : elle prend les mips
  PC à partir de 512 et les swizzle. L'en-tête de texture du jeu et le manifeste du bundle ne changent pas.
- La `.toc` donne l'emplacement (fichier cas, décalage, taille) de chaque élément de chaque bundle : on redirige
  les chunks d'une texture sans toucher au reste.
- `layout.toc` énumère chaque fichier cas existant : un nouveau `cas_NN` n'y serait pas connu. Les nouvelles données vont
  donc à la fin d'un petit cas existant, `Patch/NX/superbundlelayout/commentaryfull_eng_us/cas_01.cas` (4 Kio, toujours
  installé), livré par le mod avec ses 4 Kio d'origine devant.
- Les `.toc` sont signées (RSA, en-tête `00D1CE01`), mais **le jeu accepte une toc modifiée** : vérifié le 28/11/2026 dans
  Peanuts Native officiel avec un mod de test (deux textures de Saka échangées dans la toc : son visage change en jeu).
- En-têtes de texture Switch : même structure que sur PC (format à 0x0C, largeur/hauteur à 0x16, mips à 0x1E, GUID du
  chunk à 0x28, tailles des mips à 0x38), mêmes codes de format ; seul le mot à 0x14 diffère (0x0801 au lieu de 0x0001).
  Le swizzle de `nxtex.py` est vérifié sur la vraie texture du visage de Saka (mips 0 et 3 lisibles).
- Premier mod produit : 43 joueurs, 129 textures (couleur, normal, specmask) dans 82 bundles de `contentsb` et
  `contentlaunchsb` (Data et Patch).
- Restent à faire : les 31 visages absents de la Switch et les 37 textures de corps tatoués (2 seulement existent sur
  Switch) demandent d'ajouter des ressources et des bundles ; les maillages (forme de la tête, cheveux) ont un format
  Switch différent, à décoder.
- Le pack de ViP3eR ajoute pour 43 joueurs une variation `var_1` (nouveaux bundles) : la conversion remplace leur
  `var_0` du jeu. 31 autres visages sont des joueurs sans tête « star » sur Switch : il faudra ajouter des bundles.
- Visage seulement par défaut (couleur, normal, specmask : le dépliage UV des têtes est commun) ; les textures de
  cheveux (`--hair`) vont avec le maillage de cheveux du mod, que la Switch n'a pas.

ooz (décodeur Oodle libre, https://github.com/powzix/ooz) en bibliothèque partagée :
`g++ -O2 -fPIC -shared -w -fpermissive -o libooz.so kraken_lib.cpp lzna.cpp bitknit.cpp ooz_api.cpp`, avec un
`ooz_api.cpp` qui exporte `extern "C" int ooz_decompress(src, src_len, dst, dst_len)` (appel de `Kraken_Decompress`).

## Têtes complètes PC → Switch (en cours, 28/11/2026)

Comparé sur Bukayo Saka (sa tête du jeu Switch, `var_0`, et celle du pack PC, `var_1`) :

| Élément | PC | Switch | Conversion |
|---|---|---|---|
| EBX (toutes les déclarations d'assets) | RIFF `EBX`/`EBXD` | **identique** (mêmes tailles, mêmes structures) | aucune, sauf noms et références |
| Maillage de base (`gpudeformbasemeshasset`, res `ed27dbda`) | 2 niveaux de détail | 1 seul : **le niveau 1 du PC, octet pour octet de même format** | copier le niveau 1 du PC comme niveau 0 |
| Morphs (`headmorphblend*`, res `675fa1b1`) | 4 niveaux, encodage dense (une plage par niveau) | 3 niveaux (ceux du PC moins le premier), encodage creux (plages + sommets isolés) | retirer le niveau 0 ; l'en-tête (9 tableaux de 4 u32 par niveau, 2 listes, données float32) accepte les deux encodages |
| Cheveux, haircap (`MeshSet`, res `49b156d4`) | en-tête, puis par niveau : sommets (un flux par attribut), indices 16 bits | **même en-tête champ pour champ** | 9 flux → 7 : le PC a 8 influences d'os (le 2e groupe de 4 est toujours vide), la Switch 4 ; ajuster déclarations, tailles, offset du niveau 1, constantes 0x784→0x785 et 0x338→0x32C, nombre max d'influences 8→4 |
| Textures | BC 1024² | BC 512² block-linear | fait (`facepack2nx.py`) |

Les métadonnées de res du manifeste (16 octets) : `{u32 offset de la table de relocation, u32 sa taille, 8 octets}` ;
les 8 derniers octets sont la taille des données après l'en-tête pour un `MeshSet`, un hash (pas FNV/SHA-1/MD5 du
contenu) pour les morphs et les maillages de base. Manifeste d'un bundle : `{u32 BE taille}` puis
`{magic 9D798ED6, total, nb ebx, nb res, nb chunks, offset des chaînes}`, SHA-1 × total, (nom, taille) des ebx puis
des res, types des res, métadonnées 16 octets × res, RID 8 octets × res, chunks (GUID, offset logique, taille), chaînes.

Un joueur est relié à son bundle de tête par la table `content/common/configs/bundlereftable/starhead_brt`
(res `428ec9d4`, 1,6 Mio, dans `contentlaunchsb`) ; le FIFA Editor Tool la complète à l'installation. Ajouter une tête =
nouveau bundle (toc + manifeste), entrée dans cette table, et dans la base d'effectifs `headclasscode` 1 → 0.

