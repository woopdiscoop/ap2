# Rapport de génération — out-v2

## Résumé

- Graine : 43
- Version du rulebook : seed-draft-1
- Version des contrats : 1.3.0
- Module : 0,10 m (100 mm)
- Surface de l'emprise : 432,00 m²
- Σ surfaces nettes (programme) : 334,00 m²
- Σ surfaces placées : 338,66 m²
- Circulation : 93,34 m² (27,9 % du net ; budget 18,0 %)
- Dépassement total : 5,12 m²
- Coût total : 2000,57

## Surfaces

| ID | Nom | Type | Zone | Cible m² | Placée m² | Δ m² | Δ % | Dimensions L × l m | Façade | Statut |
|---|---|---|---|---|---|---|---|---|---|---|
| B01#01 | Bureau #01 | Bureau | Administratif | 12,00 | 12,50 | +0,50 | +4,17 | 5,00 × 2,50 | oui | OK |
| B01#02 | Bureau #02 | Bureau | Administratif | 12,00 | 12,25 | +0,25 | +2,08 | 3,50 × 3,50 | non | NO_FACADE |
| B01#03 | Bureau #03 | Bureau | Administratif | 12,00 | 12,25 | +0,25 | +2,08 | 3,50 × 3,50 | oui | OK |
| B01#04 | Bureau #04 | Bureau | Administratif | 12,00 | 12,25 | +0,25 | +2,08 | 3,50 × 3,50 | oui | OK |
| B01#05 | Bureau #05 | Bureau | Administratif | 12,00 | 12,04 | +0,04 | +0,33 | 4,30 × 2,80 | oui | OK |
| B01#06 | Bureau #06 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | non | NO_FACADE |
| B01#07 | Bureau #07 | Bureau | Administratif | 12,00 | 12,04 | +0,04 | +0,33 | 4,30 × 2,80 | oui | OK |
| B01#08 | Bureau #08 | Bureau | Administratif | 12,00 | 12,04 | +0,04 | +0,33 | 4,30 × 2,80 | oui | OK |
| B01#09 | Bureau #09 | Bureau | Administratif | 12,00 | 12,25 | +0,25 | +2,08 | 3,50 × 3,50 | non | NO_FACADE |
| B01#10 | Bureau #10 | Bureau | Administratif | 12,00 | 12,18 | +0,18 | +1,50 | 4,20 × 2,90 | oui | OK |
| B02 | Plateau | Plateau de bureaux | Administratif | 60,00 | 60,76 | +0,76 | +1,27 | 9,80 × 6,20 | oui | OK |
| H01 | Hall d'entrée | Hall d'entrée | Public | 25,00 | 25,08 | +0,08 | +0,32 | 6,60 × 3,80 | oui | OK |
| H02 | Accueil | Accueil | Public | 12,00 | 12,16 | +0,16 | +1,33 | 3,80 × 3,20 | non | REQUIRED_ADJ |
| K01 | Office | Office / kitchenette | Administratif | 8,00 | 8,12 | +0,12 | +1,50 | 2,90 × 2,80 | non | OK |
| M01#1 | Salle de réunion #1 | Salle de réunion | Administratif | 18,00 | 18,06 | +0,06 | +0,33 | 4,30 × 4,20 | oui | OK |
| M01#2 | Salle de réunion #2 | Salle de réunion | Administratif | 18,00 | 18,06 | +0,06 | +0,33 | 4,30 × 4,20 | oui | OK |
| S01#1 | Sanitaires #1 | Sanitaires | Services | 10,00 | 9,86 | -0,14 | -1,40 | 3,40 × 2,90 | oui | REQUIRED_ADJ |
| S01#2 | Sanitaires #2 | Sanitaires | Services | 10,00 | 10,20 | +0,20 | +2,00 | 3,40 × 3,00 | non | OK |
| S02 | WC PMR | Sanitaire PMR | Services | 4,00 | 4,50 | +0,50 | +12,50 | 3,00 × 1,50 | non | OK |
| T01#1 | Rangement #1 | Rangement | Services | 6,00 | 6,30 | +0,30 | +5,00 | 3,00 × 2,10 | oui | OK |
| T01#2 | Rangement #2 | Rangement | Services | 6,00 | 6,09 | +0,09 | +1,50 | 2,90 × 2,10 | oui | OK |
| T02 | Local technique | Local technique | Services | 8,00 | 8,12 | +0,12 | +1,50 | 2,90 × 2,80 | non | OK |
| T03 | Local informatique | Local informatique | Services | 6,00 | 6,09 | +0,09 | +1,50 | 2,90 × 2,10 | non | OK |
| V01 | Escalier | Escalier | Services | 18,00 | 17,68 | -0,32 | -1,78 | 5,20 × 3,40 | non | OK |
| V02 | Ascenseur | Ascenseur | Services | 5,00 | 5,78 | +0,78 | +15,60 | 3,40 × 1,70 | non | OK |

## Contraintes non respectées

### NO_FACADE (3)

- `B01#02` : B01#02: facade 0 < 24
- `B01#06` : B01#06: facade 0 < 24
- `B01#09` : B01#09: facade 0 < 24

### REQUIRED_ADJ (2)

- `H02` : H02 shares < 12 modules with every M01
- `S01#1` : S01#1 shares < 12 modules with every S02

## Coût

| Terme | Valeur | Poids | Valeur pondérée |
|---|---|---|---|
| area_overshoot | 0,02 | 1,00 | 0,02 |
| aspect | 0,00 | 1,00 | 0,00 |
| circulation_length | 0,55 | 1,00 | 0,55 |
| core_distance | 0,32 | 1,00 | 0,32 |
| facade_orientation | -0,16 | 1,00 | -0,16 |
| required_adjacency | 2,00 | 1000,00 | 2000,00 |
| rulebook_adjacency | -0,16 | 1,00 | -0,16 |
| **Total** |  |  | 2000,57 |

## Fichiers

- `layout.json` : plan généré (sérialisation canonique du contrat)
- `layout.dxf` : plan DAO en calques (DXF R2018, mètres)
- `preview.svg` : aperçu (SVG)
- `report.md` : ce rapport
