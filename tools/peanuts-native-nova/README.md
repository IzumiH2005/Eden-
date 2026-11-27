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

Rien d'autre ne change : même traduction de shaders, mêmes profils de jeux, mêmes réglages.

**Non mesuré sur un vrai Galaxy A56** : à comparer avec Peanuts Native, au même endroit et dans les mêmes
réglages (FPS, FT et 1 %L de l'overlay).

## Installer et récupérer ses jeux

Le préparateur de jeux de Nova est simulé (`-PnxPackEngine=fake`) : **on ne prépare pas un jeu dans Nova**,
on reprend celui préparé par Peanuts Native.

1. Dans **Peanuts Native** (l'officiel), sur la page du jeu : **Export pack…**, puis **Back up saves**.
2. Installer `peanuts-nova-0.1.9-a56.apk`, ouvrir **Peanuts Nova** et accorder l'accès à tous les fichiers.
3. **Add game** avec le même dossier ou fichier de jeu, puis **Import pack…** avec le zip exporté. Ne pas
   toucher **Prepare** : il produirait un pack factice qui ne démarre pas.
4. **Import save** (ou **Restore saves**) depuis `Switch2/save-backups/<title ID>/`.
5. Réinstaller le pilote GPU (radv-xclipse ou Nova) dans Settings › GPU driver.

Pour comparer les deux applications, garder les mêmes réglages : Nova active « Use fast cores » par défaut,
on peut l'activer aussi dans l'officiel, ou le couper dans Nova.

## Reconstruire

`./build-nova.sh [checkout peanuts-native]` (SDK Android avec NDK 28.2.13676358 et CMake 3.22.1 dans
`$ANDROID_HOME`, JDK 17+, python3). Le script récupère le tag `v0.1.9-1`, applique `patches/` et écrit l'APK
dans `dist/`. L'APK est signé avec une clé de débogage.

Licence : Peanuts Native est sous GPL-3.0-or-later ; ces changements aussi.
