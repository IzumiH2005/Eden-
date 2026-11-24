# eden-shader-dump

Outil hors ligne (Linux) d'EdEn.claude : relit un cache de shaders Vulkan d'Eden (`vulkan.bin`,
dans `shader/<title id>/`). Pour chaque shader du jeu, il relance le recompilateur d'Eden et écrit :

- `<hash>.<étage>.ir` : l'IR d'Eden après toutes les passes d'optimisation ;
- `<hash>.<étage>.spv` : le SPIR-V émis (convertible en GLSL avec `spirv-cross`) ;
- `index.tsv` : pipelines, étages, hashes et formats des textures de chaque shader.

Usage : `eden-shader-dump vulkan.bin dossier_sortie`

Compilation : construire les cibles `shader_recompiler` et `common` d'Eden pour l'hôte, compiler
`main.cpp` avec les mêmes options, puis lier `libshader_recompiler.a`, `libcommon.a`, sirit, fmt,
zstd, lz4 et boost. La taille de clé `GRAPHICS_KEY_SIZE` doit correspondre à
`sizeof(Vulkan::GraphicsPipelineCacheKey)` sur la plateforme qui a produit le cache (1048 sur arm64).
