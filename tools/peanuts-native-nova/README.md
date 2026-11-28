# Peanuts Nova

[Peanuts Native](https://github.com/igawa6/peanuts-native) **0.1.9** (tag `v0.1.9-1`) recompilé pour le
processeur de l'**Exynos 1580** (Galaxy A56), avec des changements qui allègent le travail du processeur.

S'installe **à côté** de Peanuts Native : application « Peanuts Nova », paquet `dev.nxnative.android.nova`,
avec ses propres données.

> Ne fonctionne que sur un processeur Armv9.2 comme celui de l'Exynos 1580.

## Pourquoi le processeur

Sur le Galaxy A56, Tears of the Kingdom tourne à 32 FPS (31 ms par image) alors que le GPU ne travaille que
20 ms par image : le GPU attend le processeur un tiers du temps. Dans Peanuts, le travail graphique passe par
une chaîne de threads :

**thread du jeu** → **replay** (traduction NVN → Vulkan, un seul cœur) → **encodeur** (appels au pilote) → **GPU**

L'étape la plus lente fixe les FPS. Le replay est la plus lourde, et ton cœur le plus rapide (Cortex-A720 à
2,9 GHz) est bien plus lent que ceux des Snapdragon sur lesquels Peanuts est réglé.

## Ce qui change

| Changement | Avant | Nova | Effet |
|---|---|---|---|
| Optimisation du moteur natif | `-O1 -g` (réglage de l'hôte Mac de développement), replay seul en `-O2` | tout en `-O2`, replay en `-O3` | appels NVN du jeu, audio, synchronisation des threads, services : moins de temps processeur |
| Processeur ciblé | armv8-a générique (tous les téléphones) | `-mcpu=cortex-a720+nosve` | instructions Armv9.2 et ordonnancement A720 ; atomiques LSE directes au lieu de boucles LL/SC (le replay et l'encodeur échangent par des atomiques des dizaines de milliers de fois par image) |
| `DM_VK_PUSH_DELTA` | actif sur Snapdragon seulement | actif aussi avec **RADV** | à chaque dessin, seules les ressources qui ont changé sont envoyées au pilote. Vérifié dans le code de radv-xclipse (`radv_init_push_descriptor_set`) : le jeu de descripteurs garde son contenu entre deux envois de même layout |
| `DM_VK_CS_WARM` | Turnip seulement | aussi avec **RADV** et le **pilote Samsung** | les shaders de calcul sont compilés à l'avance en arrière-plan, au lieu d'un blocage de 45 à 105 ms à leur premier usage |
| Use fast cores | désactivé par défaut | **activé** par défaut | le replay garde le cœur à 2,9 GHz pour lui seul ; le jeu et l'encodeur ont les trois cœurs à 2,6 GHz, jamais les petits cœurs à 1,95 GHz |
| Indicateur CPU de l'overlay | fréquence des 4 petits cœurs A520 (le groupe qui a le plus de cœurs) | fréquence des cœurs A720 à 2,6 GHz, ceux du jeu | l'indicateur dit enfin si les cœurs du jeu sont bridés par la chaleur |
| Sous-groupes des shaders de calcul (`DM_VK_SUBGROUP_SMALL`) | 64 threads, la taille Adreno | **32 threads** avec RADV et le pilote Samsung | la taille native du Xclipse. En 64, radv-xclipse n'a pas `v_permlane64` : chaque échange de données entre threads (shuffle) devient une lecture par thread, jusqu'à 64 instructions au lieu d'une. La bibliothèque de shaders est prévue pour 32 ou 64 (elle découpe ses opérations en moitiés de 32) |

Rien d'autre ne change : même traduction de shaders, mêmes profils de jeux, mêmes réglages.

## La préparation des jeux (Build)

Nova contient le vrai préparateur, reconstruit depuis le code source de la 0.1.9 (`peanuts/scripts/ondevice-stage.sh` :
Python 3.14, Capstone, lz4, le traducteur de shaders en .NET NativeAOT, SPIRV-Tools, le worker de découpe). Elle a été
vérifiée pour le Xclipse :

| Ce que la préparation fixe | Valeur | Sur Xclipse |
|---|---|---|
| Taille de sous-groupe des modules | 64 threads (Adreno) | correcte : les modules sont justes sur 32 ou 64. Seul le choix fait **au lancement** comptait, corrigé ci-dessus |
| Alignement des tampons de stockage | 64 octets | correct : l'alignement du Xclipse (RADV : 4) divise 64 |
| Décalage des coordonnées de `textureGather` | 1/512 de texel | identique à la correction qu'Eden applique sur AMD et RADV (et Samsung, fix1 d'EdEn.claude) |
| Mémoire partagée par groupe de travail | 32 Kio au plus | en dessous des 64 Kio du Xclipse |
| Nombre de workers | selon les cœurs rapides (4 sur l'Exynos 1580) puis la RAM (2 sur un téléphone de 8 Go) | déjà adapté à l'A56 |

Changer ces valeurs aurait changé la bibliothèque de shaders sans gain : les packs de l'officiel ne seraient plus
compatibles. Elles restent identiques, et l'empreinte de la bibliothèque (`DMSH_VK_CHAIN` `ed3afea18bbf`) est celle de
Peanuts Native 0.1.9 : un pack préparé par l'une des deux applications fonctionne dans l'autre.

**Non mesuré sur un vrai Galaxy A56** : à comparer avec Peanuts Native, au même endroit et dans les mêmes
réglages (FPS, FT et 1 %L de l'overlay).

## Analyse pour le modding (et plus de Build)

Nova ne prépare plus les jeux : le bouton **Build** de la fiche du jeu et **Prepare again / Build again** de sa page sont
remplacés par **« Analyser pour le modding »**. Les packs viennent de Peanuts Native officiel (**Export pack…** là-bas,
**Import pack…** ici). L'analyse lance `dm/tools/fc27probe.py all` dans le Python embarqué du préparateur, sur le `.nup` du
jeu là où il est : liste des fichiers, tables `.toc` de chaque superbundle et manifeste de chaque bundle, lus avec un
thread par cœur. Le résultat est un zip dans `Download/PeanutsNova-modding/`, à envoyer pour le travail de conversion
des mods PC. Les mods convertis sont des mods RomFS au format Switch, que Peanuts Native officiel importe (Mods).

## Installer et récupérer ses jeux

1. Installer `peanuts-nova-0.1.9-a56.apk`, ouvrir **Peanuts Nova** et accorder l'accès à tous les fichiers.
2. Ajouter le jeu et lancer **Build**, comme dans l'officiel. Pour éviter une nouvelle préparation, on peut
   aussi reprendre celle de l'officiel : **Export pack…** sur la page du jeu dans Peanuts Native, puis
   **Import pack…** dans Nova.
3. Sauvegardes : **Back up saves** dans l'officiel, puis **Import save** (ou **Restore saves**) dans Nova depuis
   `Switch2/save-backups/<title ID>/`.
4. Réinstaller le pilote GPU (radv-xclipse ou Nova) dans Settings › GPU driver.

Pour comparer les deux applications, garder les mêmes réglages : Nova active « Use fast cores » par défaut,
on peut l'activer aussi dans l'officiel, ou le couper dans Nova.

## Reconstruire

`./build-nova.sh [checkout peanuts-native]` (SDK Android avec NDK 28.2.13676358 et CMake 3.22.1 dans
`$ANDROID_HOME`, JDK 17+, python3 avec fontTools, zsh, SDK .NET 10). Le script récupère le tag `v0.1.9-1`, applique
`patches/`, construit le préparateur dans `stage-work/` et écrit l'APK dans `dist/`. L'APK est signé avec une clé de
débogage.

Licence : Peanuts Native est sous GPL-3.0-or-later ; ces changements aussi.
