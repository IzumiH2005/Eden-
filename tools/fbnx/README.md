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
