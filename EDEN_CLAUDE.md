# EdEn.claude

Fork d'Eden **v0.2.1** (tag upstream `v0.2.1`, commit `58c1e20`) avec des corrections de rendu
pour les GPU **Samsung Xclipse** (Exynos, architecture AMD RDNA), par exemple le Galaxy A56
(Exynos 1580 / Xclipse 540).

L'APK s'installe **à côté** d'Eden (nom « EdEn.claude », paquet `dev.eden.eden_emulator.claude`).

## Problème visé

Sur Xclipse, la peau des personnages devient **blanche avec un halo de bloom** ou **très sombre**
(The Witcher 3, NBA…), avec le pilote Samsung d'origine comme avec radv-xclipse.

Un halo blanc correspond à une valeur infinie, une zone noire à un NaN. Ces valeurs naissent dans
les shaders d'éclairage.

## Corrections

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
