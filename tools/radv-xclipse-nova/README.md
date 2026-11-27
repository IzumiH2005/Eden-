# RADV Xclipse Nova

Build de [radv-xclipse](https://github.com/JimVulkan/radv-xclipse) **v1.9.0** (JimVulkan, Mesa
27.0.0-devel, Vulkan 1.4.368) compilé spécialement pour l'**Exynos 1580 / Xclipse 540**
(Galaxy A56).

> Ne fonctionne que sur un processeur Armv9.2 comme celui de l'Exynos 1580. Pour tout autre
> téléphone, utiliser le build d'origine de radv-xclipse.

Sans réglage, Nova se comporte exactement comme radv-xclipse v1.9.0, compilé plus agressivement.
Le **profil Nova** (`debug.radv_xclipse_nova`) active les fonctions du Xclipse 540 que
radv-xclipse laisse de côté.

## 1. Mesurer d'abord : qui limite les FPS ?

Un pilote ne peut accélérer que le travail du GPU. Si l'émulateur attend le **processeur**
(recompilation ARM, émulation du CPU de la Switch, audio), un pilote plus rapide ne donne
**aucune** image de plus. radv-xclipse contient déjà un instrument qui tranche :

```
adb shell setprop debug.radv_xclipse_perf 1
# relancer le jeu, se placer dans la scène lente, puis :
adb logcat -s RADV_PERF
```

Toutes les 2 secondes, une ligne `[PERF] … fps=… | LIMITER=…` :

| `LIMITER=` | Signification | Ce que Nova peut faire |
|---|---|---|
| `GPU/US` | le jeu attend le GPU plus de la moitié du temps | **c'est le cas où Nova peut aider** |
| `MIXED` | attente GPU entre 20 et 50 % | gain possible, mais partiel |
| `APP CPU` | le GPU attend l'émulateur | rien : il faut alléger le CPU (réglages d'Eden, résolution n'y change rien) |
| `SHADER COMPILE` | compilation de shaders | saccades, pas un manque de puissance : elles disparaissent une fois le cache rempli |

Pour couper la mesure : `adb shell setprop debug.radv_xclipse_perf ""`. Elle ne modifie pas
le cache de shaders.

## 2. Le profil Nova

| Commande | Effet |
|---|---|
| `adb shell setprop debug.radv_xclipse_nova 1` | **wave32** partout + **WGP toujours allumés** |
| `adb shell setprop debug.radv_xclipse_nova 2` | niveau 1 + fonctions RDNA3 (**VOPD**, `v_permlane64`, `s_delay_alu`) |
| `adb shell setprop debug.radv_xclipse_nova ""` | retour au comportement d'origine |

Relancer l'application après chaque changement. Les propriétés `debug.*` disparaissent au
redémarrage du téléphone. Chaque réglage `debug.radv*` fait partie de la clé du cache de
shaders : le premier lancement après un changement recompile les shaders (saccades le temps
que le cache se remplisse), puis tout redevient fluide.

### Niveau 1 : wave32

Le devicetree de l'Exynos 1580 déclare `gc-wave-front-size = 32` : la taille de vague native
du Xclipse 540 est 32. radv-xclipse exécute pourtant tous les shaders en **wave64** (défaut
RADV), ce qui a deux coûts sur ce GPU :

- en wave64, radv-xclipse désactive `v_permlane64` sur tous les Xclipse. Chaque *shuffle* de
  sous-groupe à index variable devient alors « one readlane per lane » : **jusqu'à 64
  instructions au lieu d'une**. Eden en génère pour l'instruction `SHFL` de la Switch, et les
  shaders de Peanuts Native en utilisent aussi ;
- les petits dessins (peu de pixels, peu de sommets) occupent mal une vague de 64.

En wave32, un shuffle est une seule instruction `ds_bpermute_b32`. Le niveau 1 équivaut aux
options RADV standard `cswave32,pswave32,gewave32`, déjà testées en amont sur RDNA.

### Niveau 1 : WGP toujours allumés

Le Xclipse 540 n'a que **2 WGP** (4 CU). Le noyau Samsung (`sgpu`) les met hors tension dès
qu'ils sont inactifs (`RLC_PG_CNTL.STATIC_PER_WGP_PG_ENABLE`, masque « toujours allumé » à 0),
et les rallume au travail suivant, ce qui coûte un délai à chaque reprise. Le noyau expose un
ioctl privé (`AMDGPU_WGP_GATING`, `DRM_COMMAND_BASE + 0x5e`) qui fixe le nombre de WGP toujours
alimentés. Nova le règle à 2 tant que le jeu tourne, et le remet à 0 à la fermeture.

Le journal (`adb logcat | grep "WGP always-on"`) indique si le noyau a accepté :
`radv/xclipse nova: WGP always-on 2 -> ok (0)`. Avec `refused`, le noyau du téléphone refuse et
seul le wave32 s'applique. Coût : un peu plus de consommation au repos pendant le jeu. Réglable
seul avec `debug.radv_xclipse_wgp_aon 1`.

### Niveau 2 : fonctions RDNA3

radv-xclipse compile en jeu d'instructions GFX11 (RDNA3) mais désactive sur **tous** les
Xclipse trois fonctions mises au point sur le Xclipse 920 (RDNA2), qui ne les a pas :

| Fonction | Effet si le 540 l'a |
|---|---|
| **VOPD** (dual-issue VALU) | jusqu'à 2 opérations de calcul par cycle, en wave32 seulement (d'où le niveau 1 inclus) |
| **`v_permlane64_b32`** | shuffles rapides en wave64 (ceux qui restent, par exemple dans les shaders internes) |
| **`s_delay_alu`** | indications d'ordonnancement, moins d'attentes entre instructions dépendantes |

Personne n'a vérifié que le 540 les exécute correctement. Si le niveau 2 donne une image
cassée, un plantage ou un blocage, revenir au niveau 1. Chaque fonction reste réglable seule :
`debug.radv_xclipse_vopd`, `debug.radv_xclipse_permlane64`, `debug.radv_xclipse_delay_alu`.

## 3. Protocole de test

Toujours **dans la même scène**, cache de shaders déjà rempli (jouer une minute avant de
noter), en relevant `fps=` et `LIMITER=` du journal `RADV_PERF` :

1. référence : `setprop debug.radv_xclipse_nova ""` ;
2. `setprop debug.radv_xclipse_nova 1` ;
3. `setprop debug.radv_xclipse_nova 2`.

Garder le niveau qui donne le plus de FPS sans défaut d'image. Faire les mesures téléphone
froid : après quelques minutes de jeu, la limitation thermique (ci-dessous) fausse la
comparaison.

## 4. Ce qu'un pilote ne peut pas changer

L'analyse du noyau Samsung de l'Exynos 1580 (`drivers/gpu/drm/sgpu`, `s5e8855-sgpu.dtsi`) montre
que les autres leviers sont déjà utilisés, ou hors de portée d'un pilote Vulkan :

| Mécanisme | Constat |
|---|---|
| Fréquence GPU (102 à 1408 MHz) | le gouverneur du noyau la monte d'après le temps où le GPU a du travail en cours. Quand le GPU limite, il est déjà au maximum. Un pilote ne peut pas la forcer. |
| Cache LLC du SoC | déjà attribué au GPU par le noyau (16 voies au-delà de 544 MHz, réglages « golden » `GL2ACEM_LLC_MTY0_CTRL` pour la mémoire de type 0 qu'utilise RADV). Rien à gagner. |
| `cl_boost` (1,3 GHz) | réservé aux charges 100 % compute (OpenCL), jamais actif en jeu. |
| **GVF** (limitation thermique) | le noyau insère des périodes d'inactivité forcée quand le GPU chauffe. C'est la cause la plus probable des chutes de FPS au bout de quelques minutes. Seul le refroidissement y peut quelque chose (coque retirée, ventilateur, pièce fraîche). |

## 5. Ce qui change par rapport à radv-xclipse

| | radv-xclipse | Nova |
|---|---|---|
| Optimisation | `debugoptimized` (`-O2 -g`) | `release` (`-O3`) |
| Optimisation à l'édition de liens (LTO) | non | non : Mesa la refuse explicitement (« Building Mesa with LTO is not supported ») |
| Processeur ciblé | `-march=armv8.2-a`, générique, tous les Exynos | `-mcpu=cortex-a720+nosve` : instructions et ordonnancement A720/A520, sans vectorisation SVE (aucun gain pour ce code, et un risque de plantage si le noyau ne l'expose pas) |
| Profil Nova | — | `debug.radv_xclipse_nova` 1 / 2, désactivé par défaut |

La compilation seule réduit le coût CPU du pilote (enregistrement des commandes, compilation
des shaders par ACO, donc un peu moins de saccades) : quelques pourcents du temps passé dans le
pilote. **Aucune de ces modifications n'a été mesurée sur un vrai Xclipse** : à comparer
soi-même avec le protocole ci-dessus.

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
encore lancé Peanuts Native sur un Xclipse : c'est à tester. Peanuts Native demande aussi 12 Go
de RAM, le Galaxy A56 en a 8.

## Installer

Importer le zip comme pilote GPU personnalisé (Eden : gestionnaire de pilotes ; Peanuts Native :
Settings › GPU driver › Install, fichier zip). En cas de problème, effacer les propriétés
`debug.radv_xclipse_*` ou revenir au zip radv-xclipse v1.9.0 d'origine.

## Reconstruire

`./build-nova.sh <android-ndk> [checkout radv-xclipse]` (NDK r28+, meson ≥ 1.4, ninja, mako,
glslangValidator). Le script récupère radv-xclipse v1.9.0, applique `patches/` et écrit le zip
dans `dist/`.
