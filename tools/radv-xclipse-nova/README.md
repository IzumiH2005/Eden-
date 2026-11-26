# RADV Xclipse Nova

Build de [radv-xclipse](https://github.com/JimVulkan/radv-xclipse) **v1.9.0** (JimVulkan, Mesa
27.0.0-devel, Vulkan 1.4.368) compilé spécialement pour l'**Exynos 1580 / Xclipse 540**
(Galaxy A56).

> Ne fonctionne que sur un processeur Armv9.2 comme celui de l'Exynos 1580. Pour tout autre
> téléphone, utiliser le build d'origine de radv-xclipse.

## Ce qui change par rapport à radv-xclipse

Le code du pilote est **identique** à la v1.9.0. Seule la compilation change :

| | radv-xclipse | Nova |
|---|---|---|
| Optimisation | `debugoptimized` (`-O2 -g`) | `release` (`-O3`) |
| Optimisation à l'édition de liens (LTO) | non | non : Mesa la refuse explicitement (« Building Mesa with LTO is not supported ») |
| Processeur ciblé | `-march=armv8.2-a`, générique, tous les Exynos | `-mcpu=cortex-a720+nosve` : instructions et ordonnancement A720/A520, sans vectorisation SVE (aucun gain pour ce code, et un risque de plantage si le noyau ne l'expose pas) |

Effet attendu : un coût CPU plus faible pour tout ce que le pilote fait sur le processeur. Cela
couvre l'enregistrement des commandes, les descripteurs et surtout la **compilation des shaders
par ACO**, donc moins de saccades à la première rencontre d'un shader. Le gain attendu est
**faible** : quelques pourcents du temps passé dans le pilote, souvent moins. Le travail du GPU
lui-même n'est pas plus rapide. **Non mesuré sur un vrai Xclipse** : à comparer soi-même.

## Analyse faite

### Comparaison avec Turnip

Turnip (pilote Mesa des Adreno) doit ses performances à des mécanismes propres à l'architecture
Adreno : rendu par tuiles en GMEM, LRZ, UBWC, réglage des bins. Rien de cela n'existe sur un GPU
RDNA comme le Xclipse. L'équivalent de Turnip pour cette architecture est **RADV/ACO**, le pilote
AMD de Mesa (Valve), et radv-xclipse en est déjà un portage. Le chemin CPU de RADV est déjà très
optimisé en amont, et la journalisation et les statistiques ajoutées par radv-xclipse sont
désactivées ou presque gratuites par défaut. Aucun gaspillage évident n'a été trouvé à supprimer
dans le code.

### Compatibilité avec Peanuts Native

D'après sa section « GPUs other than Adreno », Peanuts Native (testé seulement sur Snapdragon)
a besoin, sur un autre GPU, de :

| Exigence de Peanuts Native | radv-xclipse / Nova |
|---|---|
| `VK_EXT_map_memory_placed` (sinon écran noir) | **oui** (`memoryMapPlaced`, `memoryUnmapReserve`) |
| Mémoire device-local + host-visible + coherent + **cached** (sinon lectures CPU lentes) | **oui** (type GTT en cache, marqué device-local sur Xclipse) |
| Textures BC1-BC7 natives | oui : BC1-3 en matériel, BC4-7 émulées par le pilote (conversion avec perte par défaut, voir les options `debug.radv_xclipse_*`) |
| Push descriptors, vertex input dynamic state, null descriptors, update-after-bind, timeline semaphores | oui |
| Sous-groupes de 32 ou 64 | oui (RDNA : 32/64) |
| Float64, geometry, tessellation, lecture d'images sans format | oui |

Le pilote Samsung d'origine n'a probablement pas `VK_EXT_map_memory_placed` : avec lui, Peanuts
Native risque l'écran noir. radv-xclipse/Nova coche toutes les cases connues, mais personne n'a
encore lancé Peanuts Native sur un Xclipse : c'est à tester.

## Tester

1. Importer le zip comme pilote GPU personnalisé (Eden : gestionnaire de pilotes ; Peanuts
   Native : Settings › GPU driver › Install, fichier zip).
2. Comparer avec le zip radv-xclipse v1.9.0 d'origine **dans la même scène** : FPS moyen, et
   surtout saccades à la première ouverture d'une zone (compilation de shaders).
3. En cas de problème, revenir au build d'origine : le code GPU est le même, seule la
   compilation diffère.

## Reconstruire

`./build-nova.sh <android-ndk> [checkout radv-xclipse]` (NDK r28+, meson ≥ 1.4, ninja, mako,
glslangValidator). Le script récupère radv-xclipse v1.9.0, applique `patches/` et écrit le zip
dans `dist/`.
