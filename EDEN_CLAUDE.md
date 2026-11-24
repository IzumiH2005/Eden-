# EdEn.claude

Fork d'Eden **v0.2.1** (tag upstream `v0.2.1`, commit `58c1e20`) avec des corrections de rendu
pour les GPU **Samsung Xclipse** (Exynos, architecture AMD RDNA), par exemple le Galaxy A56
(Exynos 1580 / Xclipse 540).

L'APK s'installe **à côté** d'Eden (nom « EdEn.claude », paquet `dev.eden.eden_emulator.claude`).

## Correction fix6 : erreurs révélées par la validation Vulkan

Le journal avec « Débogage des graphismes » (validation Vulkan) et le cache de shaders de The
Witcher 3, analysé avec `tools/eden-shader-dump`, montrent deux erreurs qui n'existent que sur
Xclipse.

**A. Filtrage linéaire sur des formats non filtrables.** Le D24S8 de la Switch est émulé en
`D32_SFLOAT_S8_UINT` sur Xclipse, et ce format, comme `R32_SFLOAT`, `R32G32B32A32_SFLOAT`,
`R16_UNORM` et les formats entiers, ne supporte pas le filtrage linéaire sur ce GPU. Les shaders
qui lisent la profondeur (reconstruction de distance, passes plein écran, compute) obtenaient
donc des valeurs indéfinies. Correction : chaque échantillonneur a désormais une variante
« nearest », utilisée automatiquement avec les vues dont le format n'est pas filtrable
(`vk_texture_cache.cpp/.h`, `pipeline_helper.h`).

**B. Textures entières lues par un échantillonneur flottant.** Une texture `R16_UINT` sert
d'index : 16 bits découpés en champs (`bitfieldExtract`) qui servent d'indices dans les tables
de paramètres de matériau (shader `d9d4102bbe644ac1`, qui écrit 3 cibles de type G-buffer).
Eden la déclarait comme une texture flottante, ce qui est indéfini en Vulkan. Si le GPU convertit
l'entier en flottant au lieu de rendre les bits bruts, les indices de matériau sont faux.
Correction : les textures au format entier sont déclarées en `usampler`/`isampler`, et leurs
résultats sont rendus au shader bit pour bit (`texture_pass.cpp`, `shader_info.h`,
`spirv_emit_context.*`, `emit_spirv_image.cpp`). Le cache de shaders passe en version 18, donc
les anciens caches sont reconstruits.

Vérification hors ligne : les 316 shaders du jeu, recompilés en forçant toutes les textures en
entier, restent du SPIR-V valide (`spirv-val`, mêmes résultats qu'avant la modification).

## Problème visé

Sur Xclipse, la peau des personnages devient **blanche avec un halo de bloom** ou **très sombre**
(The Witcher 3, NBA…), avec le pilote Samsung d'origine comme avec radv-xclipse.

Un halo blanc correspond à une valeur infinie, une zone noire à un NaN. Ces valeurs naissent dans
les shaders d'éclairage.

## Diagnostic fix4 : chemins « Adreno » forcés

Les tests fix1 à fix3 ont éliminé le FP16, les NaN, les conversions profondeur → couleur (jamais
demandées par The Witcher 3) et le décodeur ASTC matériel. Le bug n'existe pas sur Snapdragon,
donc la fix4 ajoute six options, **toutes activées par défaut**. Chacune fait prendre à Eden, sur
Xclipse, le chemin qu'il prend sur Adreno :

| Option | Effet |
|---|---|
| Diag A | formats de sommets USCALED/SSCALED émulés dans les shaders |
| Diag B | `VK_KHR_shader_float_controls` retiré |
| Diag C | pas de décalage sous-pixel AMD pour `textureGather` |
| Diag D | `VK_EXT_depth_clip_control` retiré |
| Diag E | `VK_EXT_shader_stencil_export` retiré |
| Diag F | entiers 64 bits et leurs atomiques retirés |

Si la peau est corrigée avec tout activé, désactiver une option à la fois pour trouver la coupable.
« Décodage ASTC logiciel » est désormais désactivé par défaut (aucun effet constaté).

## Test fix3 : décodage ASTC logiciel sur Xclipse

Sur Xclipse, la peau se corrompt **quand on s'approche** d'un personnage, c'est-à-dire quand les
niveaux de détail haute résolution de ses textures sont chargés. Le Xclipse est le seul GPU
d'architecture AMD qui décode l'ASTC, avec un bloc matériel Samsung utilisé par le pilote Samsung
comme par radv-xclipse. Les deux pilotes présentent le même bug.

L'option **« Décodage ASTC logiciel sur Xclipse »** (activée par défaut) masque l'ASTC natif :
Eden décode alors les textures ASTC lui-même sur le GPU, comme sur les PC sans ASTC.
Fichier : `vulkan_device.cpp`.

## Correction fix2 : conversions profondeur → couleur rétablies

Le commit Eden `3e835ac3aa` (« Add new shader format conversion pipelines », 1er février 2025) a
réécrit `TextureCacheRuntime::ConvertImage` et supprimé les conversions profondeur → couleur
héritées de yuzu (`D24S8 → RGBA8`, `D32 → RGBA8`, `D32 → R32`, `D16 → R16`, `RGBA8 → S8D24`…),
alors que les shaders et les fonctions de conversion existent toujours.

`TextureCache::CopyImage` n'envoie ces copies à `ConvertImage` que sur les GPU qui ont
`VK_EXT_shader_stencil_export` : AMD, NVIDIA et **Samsung Xclipse**, jamais Adreno (qui passe par
`ReinterpretImage`). Sur Xclipse, chaque fois qu'un jeu relisait sa profondeur comme une texture
couleur (éclairage différé, diffusion sous la peau, SSAO…), Eden **ne faisait rien**. Le jeu lisait
alors une image périmée ou vide, d'où une peau blanche ou au mauvais teint.

Fichier : `src/video_core/renderer_vulkan/vk_texture_cache.cpp`. Les conversions encore non gérées
sont désormais signalées une fois chacune dans le journal (`Unimplemented texture conversion`).

## Corrections précédentes (fix1)

| Correction | Fichiers | Option Android |
|---|---|---|
| Calcul FP16 du jeu exécuté en FP32 sur les GPU d'architecture AMD (Xclipse inclus). Eden upstream ne le fait que pour les pilotes AMD de bureau, alors que les Xclipse ont le même problème. Le FP32 respecte aussi l'arrondi des dénormaux à zéro de la Switch, que les pilotes Xclipse ne savent pas appliquer en FP16. | `vulkan_device.cpp/.h` | **Shaders FP32 sur Xclipse/AMD** (activée par défaut) |
| `min`/`max`/`clamp`/`saturate` traduits avec `NMin`/`NMax`, pour reproduire exactement le GPU Maxwell face aux NaN : l'opérande non-NaN gagne et `saturate(NaN) = 0`. `FMin`/`FMax`/`FClamp` laissent ce cas indéfini. | `emit_spirv_floating_point.cpp`, `profile.h`, `vk_pipeline_cache.cpp` | **Calcul anti-NaN sur Xclipse/AMD** (activée par défaut) |
| Correction de l'arrondi des coordonnées de `textureGather` appliquée aussi au pilote Samsung, comme Eden le fait déjà pour AMD et RADV. | `vk_pipeline_cache.cpp` | automatique |
| Le hack « GPU Unswizzle » ne copie plus des blocs BCn bruts dans une texture déjà décodée par le CPU. Ce cas produisait des textures corrompues sur les GPU sans BCn natif. | `texture_cache.h` | automatique |

Les deux options se trouvent dans **Paramètres → Vidéo**, section **Contournements** (« Hacks » en anglais). Elles sont aussi réglables
**par jeu**. Il faut relancer le jeu après les avoir modifiées.

## Tester

1. Lance The Witcher 3 ou NBA avec les deux options activées (réglage par défaut).
2. Si la peau est corrigée, désactive une option à la fois pour savoir laquelle a fait la
   différence (utile pour signaler le bug à Eden).

## Compilation

`./gradlew assembleClaudeRelease` dans `src/android` (APK dans `src/android/app/build/outputs/apk/claude/release/`).
