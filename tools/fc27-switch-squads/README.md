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

## Limites

- Le format exact de la sauvegarde Switch (INDEX / DATA) n'est pas documenté publiquement. La découpe
  écrite par `fetch` est déduite du format PC et des descriptions de la communauté. `patch-save` vérifie la
  disposition réelle avant d'écrire.
- La base suit la dernière mise à jour du jeu : FC 27 doit être à jour dans Eden.
- Un fichier d'effectifs ne change rien aux performances : il ne contient que les données des joueurs et des
  équipes.
