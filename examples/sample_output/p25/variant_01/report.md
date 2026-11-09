# Rapport de génération — out-v1

## Résumé

- Graine : 42
- Version du rulebook : seed-draft-1
- Version des contrats : 1.3.0
- Module : 0,10 m (100 mm)
- Surface de l'emprise : 432,00 m²
- Σ surfaces nettes (programme) : 334,00 m²
- Σ surfaces placées : 336,81 m²
- Circulation : 95,19 m² (28,5 % du net ; budget 18,0 %)
- Dépassement total : 2,81 m²
- Coût total : 3000,52

## Surfaces

| ID | Nom | Type | Zone | Cible m² | Placée m² | Δ m² | Δ % | Dimensions L × l m | Façade | Statut |
|---|---|---|---|---|---|---|---|---|---|---|
| B01#01 | Bureau #01 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B01#02 | Bureau #02 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B01#03 | Bureau #03 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B01#04 | Bureau #04 | Bureau | Administratif | 12,00 | 12,04 | +0,04 | +0,33 | 4,30 × 2,80 | oui | OK |
| B01#05 | Bureau #05 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | non | NO_FACADE |
| B01#06 | Bureau #06 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B01#07 | Bureau #07 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B01#08 | Bureau #08 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B01#09 | Bureau #09 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | non | NO_FACADE |
| B01#10 | Bureau #10 | Bureau | Administratif | 12,00 | 12,00 | +0,00 | +0,00 | 4,80 × 2,50 | oui | OK |
| B02 | Plateau | Plateau de bureaux | Administratif | 60,00 | 60,50 | +0,50 | +0,83 | 11,00 × 5,50 | oui | OK |
| H01 | Hall d'entrée | Hall d'entrée | Public | 25,00 | 25,30 | +0,30 | +1,20 | 5,50 × 4,60 | oui | REQUIRED_ADJ |
| H02 | Accueil | Accueil | Public | 12,00 | 12,50 | +0,50 | +4,17 | 5,00 × 2,50 | non | REQUIRED_ADJ |
| K01 | Office | Office / kitchenette | Administratif | 8,00 | 8,00 | +0,00 | +0,00 | 3,20 × 2,50 | non | OK |
| M01#1 | Salle de réunion #1 | Salle de réunion | Administratif | 18,00 | 18,24 | +0,24 | +1,33 | 4,80 × 3,80 | oui | OK |
| M01#2 | Salle de réunion #2 | Salle de réunion | Administratif | 18,00 | 18,24 | +0,24 | +1,33 | 4,80 × 3,80 | oui | OK |
| S01#1 | Sanitaires #1 | Sanitaires | Services | 10,00 | 10,08 | +0,08 | +0,80 | 3,60 × 2,80 | non | OK |
| S01#2 | Sanitaires #2 | Sanitaires | Services | 10,00 | 10,08 | +0,08 | +0,80 | 3,60 × 2,80 | non | OK |
| S02 | WC PMR | Sanitaire PMR | Services | 4,00 | 4,20 | +0,20 | +5,00 | 2,80 × 1,50 | non | OK |
| T01#1 | Rangement #1 | Rangement | Services | 6,00 | 6,00 | +0,00 | +0,00 | 2,50 × 2,40 | non | OK |
| T01#2 | Rangement #2 | Rangement | Services | 6,00 | 6,16 | +0,16 | +2,67 | 2,80 × 2,20 | non | OK |
| T02 | Local technique | Local technique | Services | 8,00 | 8,12 | +0,12 | +1,50 | 2,90 × 2,80 | non | OK |
| T03 | Local informatique | Local informatique | Services | 6,00 | 6,16 | +0,16 | +2,67 | 2,80 × 2,20 | non | OK |
| V01 | Escalier | Escalier | Services | 18,00 | 18,15 | +0,15 | +0,83 | 5,50 × 3,30 | oui | REQUIRED_ADJ |
| V02 | Ascenseur | Ascenseur | Services | 5,00 | 5,04 | +0,04 | +0,80 | 2,80 × 1,80 | non | OK |

## Contraintes non respectées

### NO_FACADE (2)

- `B01#05` : B01#05: facade 0 < 24
- `B01#09` : B01#09: facade 0 < 24

### REQUIRED_ADJ (3)

- `H01` : H01 shares < 12 modules with every V02
- `H02` : H02 shares < 12 modules with every M01
- `V01` : V01 shares < 12 modules with every V02

## Coût

| Terme | Valeur | Poids | Valeur pondérée |
|---|---|---|---|
| area_overshoot | 0,01 | 1,00 | 0,01 |
| aspect | 0,00 | 1,00 | 0,00 |
| circulation_length | 0,58 | 1,00 | 0,58 |
| core_distance | 0,14 | 1,00 | 0,14 |
| facade_orientation | -0,06 | 1,00 | -0,06 |
| required_adjacency | 3,00 | 1000,00 | 3000,00 |
| rulebook_adjacency | -0,16 | 1,00 | -0,16 |
| **Total** |  |  | 3000,52 |

## Fichiers

- `layout.json` : plan généré (sérialisation canonique du contrat)
- `layout.dxf` : plan DAO en calques (DXF R2018, mètres)
- `preview.svg` : aperçu (SVG)
- `report.md` : ce rapport
