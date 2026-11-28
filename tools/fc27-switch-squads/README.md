# Effectifs FC 27 pour la Switch (Eden)

`fc27_switch_squads.py` produit la mise à jour officielle des effectifs d'EA SPORTS FC 27 **au format de la
Switch**, et sait l'installer dans une sauvegarde exportée par Eden.

## Pourquoi un fichier PC ne marche pas sur Switch

Les fichiers d'effectifs qui circulent (« Squads2026… », installés dans `AppData\Local\EA SPORTS FC 27\settings`)
sont ceux de la version **PC**. L'index officiel d'EA (`rosterupdate.xml`) publie chaque mise à jour en deux familles
de bases de données :

| Plateformes | Schéma | Tables |
|---|---|---|
| PC, PS5, Xbox Series, Switch 2 | `b41ea024…` | 82 |
| **Switch**, PS4, Xbox One | `6540b642…` | 81 : pas de table `xscJ`, et `Vmkr`, `OIcD`, `xuka`, `PViY`, `DbIl` différentes |

FC 27 sur Switch (donc sur Eden) attend la seconde. Le script prend directement la base Switch sur les serveurs
d'EA (plateforme `nx`), plutôt que de convertir la base PC.

## Ce que fait le script

1. Lit `rosterupdate.xml` et télécharge la dernière base de la plateforme demandée (par défaut `nx`).
2. La décompresse (RefPack d'EA) et vérifie ses propres sommes de contrôle : CRC-32/MPEG-2 de l'en-tête et du
   répertoire des tables.
3. L'emballe dans le conteneur des fichiers d'effectifs, octet pour octet comme le fait
   [xAranaktu/FIFASquadFileDownloader](https://github.com/xAranaktu/FIFASquadFileDownloader) (vérifié : le fichier
   PC fourni par l'utilisateur est reconstruit à l'identique).
4. Écrit le fichier entier et sa découpe Switch supposée : `INDEX` (le préfixe de 1126 octets : FBCHUNKS, nom,
   taille) et `DATA` (le reste, qui commence par `SaveType_Squads`).

```
python3 fc27_switch_squads.py fetch --out out                  # out/Squads<date>000000, out/switch/INDEX, out/switch/DATA
python3 fc27_switch_squads.py inspect <fichier ou export.zip>  # plateforme de la base, contenu d'une sauvegarde
python3 fc27_switch_squads.py patch-save export.zip out/Squads<date>000000 import.zip
```

`patch-save` repère dans l'export Eden le dossier dont le `DATA` contient `SaveType_Squads`, vérifie sa
disposition (INDEX + DATA séparés, ou fichier entier dans DATA), remplace ce seul emplacement et garde tout le
reste. Il refuse sans rien écrire une disposition inconnue, une sauvegarde sans effectifs et une base PC.

## Format réel de la sauvegarde Switch (lu le 28/11/2026 sur une vraie sauvegarde FC 27)

Chaque élément sauvegardé est un dossier `main/<FNV-1 32 bits du nom, 8 chiffres hexa>/` avec trois fichiers :

| Fichier | Contenu |
|---|---|
| `name` | le nom de l'élément, sans NUL (`Squads20261123000000`, `Settings…`, `UCLTrnmnt…`) |
| `INDEX` | 3 entrées de 0x50 octets `{nom[32], u64 1, u64 taille, u64 début, u64 fin, 16 zéros}` : body, displayname, header |
| `DATA` | les sections displayname, header (0x404 octets), body, chacune `{u64 longueur après ces 16 octets, u64 heure en ns Unix, contenu}` |

Le body commence par l'en-tête de 48 octets `{"SaveType_<type>\0", u32 CRC-32 zlib du body à partir de l'octet 64,
u32 0x31c, u32 1, zéros}` ; pour les effectifs viennent ensuite, comme dans le fichier PC, la taille, la base T3DB et le
bloc BNRY. `switch_item()` écrit un tel élément et `check_item()` relit un élément comme le jeu (vérifié sur les éléments
d'une vraie sauvegarde). La découpe `switch/INDEX` + `switch/DATA` des premières versions était une hypothèse fausse.

## Limites

- La base suit la dernière mise à jour du jeu : FC 27 doit être à jour dans Eden.
- Un fichier d'effectifs ne change rien aux performances : il ne contient que les données des joueurs et des
  équipes.
