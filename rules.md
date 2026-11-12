---
type: Project Rules
title: Règles de juni-bug-tracker
description: Règles communes aux bug trackers et particularités de Junos OS et Junos OS Evolved.
resource: https://github.com/frc-fr/juni-bug-tracker
tags: [rules, junos, juniper, hpe, bug-tracker]
timestamp: 2026-11-09T18:30:00+01:00
product: Junos OS, Junos OS Evolved
site: https://frc-fr.github.io/juni-bug-tracker/
---

# Critères communs

Section identique dans forti-, juni-, palo-, cisco- et f5-bug-tracker. Toute modification se reporte dans les cinq.

## Architecture

- Site statique : pas de serveur, pas de base de données.
- Python côté collecte, JavaScript sans framework côté navigateur.
- Paquet Python `<fournisseur>bugs`, une commande par étape :
  - `collect` : met à jour l'état des sources et télécharge ce qui a changé.
  - `extract` : lit les documents en cache ; échoue au moindre avertissement.
  - `build` : croise les données et génère `dist/`.
- Modules : `collect`, `parser`, `extract`, `normalize` (matériel), `lifecycle` (dates de support), `build`, `feed`, `cli`.

### Répertoires

- `sources/` : état des sources (adresses, ETag, lastmod, dates de support). Commité.
- `.cache/` : documents bruts. Non versionné, gardé par le cache de la CI.
- `data/extracted/` : un JSON par document, une ligne par bug pour des diffs lisibles. Commité.
- `data/changes.json` : journal des nouveautés. Absent au départ : la première extraction sert de référence.
- `site/` : `index.html`, `app.js` (affichage), `logic.js` (règles de statut, testables), `i18n.js`, `theme.js`, `style.css`, mentions légales FR/EN.
- `dist/` : site généré, avec `data/*.json` compacts et `feed.xml`. Non versionné.

### Modèle de données

- Un bug = identifiant, description, contournement, matériel cité, événements.
- Un événement = version, statut (`r` corrigé, `k` connu, `l` limitation…), page officielle.
- Les statuts par version sont calculés dans le navigateur, à partir des notes de la branche.

### Tests

- `pytest` : tests unitaires, plus tests sur les vrais documents en cache.
- `node --test tests/site/logic.test.js` : règles de statut et de comparaison.
- Test des clés de traduction et de la CSP.

## Sources et collecte

- Sources officielles et publiques du fournisseur en priorité.
- Source communautaire (ex. endoflife.date) seulement à défaut d'équivalent officiel, citée comme telle dans les mentions légales.
- robots.txt respecté : un chemin interdit n'est jamais interrogé.
- 2 secondes minimum entre deux requêtes, User-Agent du projet.
- Ne recharger que ce qui a changé (ETag, Last-Modified, lastmod du sitemap).
- Résultats d'extraction commités dans `data/` : vider le cache CI ne relance pas tout.
- Un avertissement d'extraction arrête la mise à jour : le site garde ses dernières données valides.
- Une source annexe (dates de support…) en échec garde ses dernières valeurs.
- Le navigateur ne contacte jamais de service tiers.

## Contenu

- Objet : bugs connus et bugs corrigés. Jamais la sécurité.
- Entrées de sécurité écartées, références CVE retirées des descriptions.
- Chaque fait renvoie à la page officielle exacte qui le porte.
- Textes des bugs laissés en anglais, tels que publiés.
- Statuts déduits des notes, jamais inventés ; « Inconnu » expliqué et masqué par défaut.
- Un modèle cité ne veut pas dire « seul ce modèle est touché ». Filtre matériel inclusif.
- Un bug à la fois correction et changement de comportement n'est compté qu'une fois.
- Une version annoncée mais pas encore publiée est marquée « non publiée ».
- Toutes les branches restent consultables ; les branches supportées sont mises en avant.
- Pas d'affirmation générale ou trop assurée dans les textes.

## Interface

- Français et anglais, sans page /en/ séparée.
- Bandeau visible : « vos sélections ne sont ni enregistrées ni transmises ».
- Onglets : Rechercher, Comparer, Matériel, puis Quoi de neuf à droite de Matériel.
- Comparaison : pastilles triées par ordre alphabétique, « Tous » en premier.
- Libellé court « Correction » ; risques (nouveaux, toujours présents) mis en valeur.
- Panneau « À lire » replié par défaut, il ne s'ouvre que si l'utilisateur le déplie.
- Listes déroulantes filtrables à la frappe ; bouton Réinitialiser.
- Tableau sélectionnable en entier et bouton « Copier le tableau ».
- Bouton de retour en haut de page.
- Logos RSS puis GitHub, minimalistes et presque transparents, à gauche de « EN ».
- Thème clair et sombre ; pas de noir trop profond.
- Textes longs justifiés, sur toute la largeur.
- Cron et date de dernière mise à jour affichés.
- Placeholders neutres : ne jamais révéler le matériel de l'utilisateur.
- Même forme dans tous les sites, quelle que soit la façon de présenter du fournisseur : on cherche au même endroit.
- Données uniformes entre fournisseurs : pas d'information propre à un seul fournisseur si elle n'aide pas l'exploitation (ex. date de mise en vente).
- Plusieurs systèmes : sélecteur de logiciel, libellé visible « Logiciel », jamais un choix de matériel.

## Matériel et nouveautés

- Onglet Matériel : pastilles de statut (« Tous » en premier, puis « Plus dans la dernière branche » ou son équivalent).
- Colonnes : Modèle, Première version, Dernière version, Statut <logiciel>, Version recommandée, Fin de support.
- Statut tiré d'une source officielle du fournisseur : il dit, sans le deviner, si le matériel est encore maintenu.
- Fin de vie annoncée par référence : variantes affichées séparément, pièces détachées et modules écartés.
- Pas de source : « Aucune fin annoncée », jamais « supporté ».
- Version recommandée seulement si le fournisseur la publie sans compte ; sinon la colonne est absente, et la note dit pourquoi.
- Rechercher : un modèle choisi affiche ce que le fournisseur dit de lui (statut, version recommandée, fin de support).
- Quoi de neuf : cartes « Dernière version publiée », « Dernier document mis à jour », puis « Recommandée par <fournisseur> » si elle existe.

## Design

- Même structure et mêmes jetons de couleur dans les trois sites.
- Couleur du fournisseur en touche seulement : bordure haute et nom du produit.
- Contraste professionnel, rien qui « pique les yeux ».
- Cohérence entre pages : mêmes pastilles partout, pas de tuiles géantes.

## Publication

- Cron du lundi au vendredi : 9 h 15, 14 h 15, 19 h 00, Europe/Paris.
- Horaire décrit dans `sources/schedule.yml` et affiché sur le site, qui le lit au build.
- Workflow GitHub sans déclencheur `schedule` (retardé ou oublié par GitHub) : lancé par `workflow_dispatch`.
- Ordre : tests, collecte, extraction, tests sur le corpus réel, commit des données, build, GitHub Pages.
- Flux RSS/Atom des nouveautés.
- CSP stricte : aucun script, style ou service tiers.

## Mentions et licence

- Outil créé et maintenu par FR Consulting ; contact@fr-consulting.fr ; lien vers fr-consulting.fr.
- Site indépendant, non affilié au fournisseur. Jamais « approuvé par ».
- Mentions légales FR et EN, avec la liste des services et composants tiers.
- Code sous AGPL 3.0 ou ultérieure ; contenus du fournisseur exclus.
- README générique : rien de sensible ni de personnel.

# Particularités Junos

## Deux systèmes

- Junos OS et Junos OS Evolved : données séparées, sélecteur en haut de page.
- Numéros partagés : le système fait partie de la clé.
- En Evolved, toujours afficher le suffixe `-EVO` (`24.4R2-S5-EVO`) : l'utilisateur ne doit pas confondre.

## Versions

- Version R : `25.4R1`, `25.4R2`. Une note PDF par version R.
- Version de service -S : `22.2R3-S7`. Équivalent des builds FortiOS, avec corrections de bugs.
- Une correction en `22.2R3-S7` vaut pour `22.2R3-S8`, pas pour `22.2R2-Sx` ni pour `22.2R4`.
- Une -S hérite des problèmes ouverts de sa version R : « Potentiellement affecté ».
- -S citée dans « Resolved In » sans article : « non publiée » si elle suit la dernière -S publiée.
- Chemin de mise à niveau : R1 de chaque branche suivante, puis la branche cible.
- Prendre en compte la dernière version basse qui permet de passer en version supportée.

## Sources

- PDF sur networkingdocs.hpe.com, à une adresse prévisible. Adresse différente à partir de 26.2 (HPE).
- Aucune page parcourue : HEAD sur les PDF connus, et sur quelques adresses candidates.
- www.juniper.net jamais interrogé : robots.txt interdit. Entrée `"manual": true` téléchargée une fois.
- Articles SRN des -S sur supportportal.juniper.net : sitemap, puis HEAD sur l'adresse prévisible.
- Articles rendus par Lightpanda (JavaScript). Seulement « Fixed issues » et « Known issues ».
- Partie « Confidential », entrées de sécurité et notes internes jamais lues.
- Article rendu seulement s'il est nouveau ou si son lastmod a changé.
- SRN illisible (vide, pièce jointe, texte d'une autre version) : raison affichée, statuts partiels.
- PDF de SRN déposés à la main dans `.cache/srn-attachments` : lus après l'article.
- Lien vers l'article SRN, pas vers le PDF.
- Dates de support : page Junos OS Dates & Milestones. Pas de table Evolved : mêmes dates, réserve affichée.

## Matériel

- Chaque PR est dans le chapitre d'une famille (MX Series, EX Series…) : famille fiable.
- Modèle connu seulement quand le texte le cite.
- Avec un modèle choisi : PR qui le citent, puis PR de sa famille sans modèle cité.
- Fin de vie : tableaux « Hardware Dates & Milestones » des séries ACX, EX, MX (page M Series), NFX, PTX, QFX, SRX.
- Annonces SKU par SKU : seuls les châssis comptent, une alimentation ou un ventilateur ne dit rien du modèle.
- Une variante (EX4300-32F) peut s'arrêter avant les autres : chaque variante est affichée.
- « Arrêt après » : LSV avant la dernière branche publiée, ou fin de support passée.
- Version suggérée : article KB21476, rendu par Lightpanda. « (LSV) » complète une annonce sans LSV.
- Une ligne KB21476 avec `-EVO` relève d'Evolved ; les annonces sans système vont à Junos OS.
- Carte « Suggérée par Juniper » : versions des branches encore supportées seulement.

## Affichage

- Identifiants préfixés `PR`.
- Sévérité Juniper affichée, avec lien vers les définitions Juniper en pied de page.
- « What's Changed » des notes traversées dans la comparaison.

# Citations

[1] [SRN Definitions of Severity](https://supportportal.juniper.net/s/article/SRN-Definitions-of-Severity)
[2] [Junos OS Dates & Milestones](https://support.juniper.net/support/eol/software/junos/)
[3] [Lightpanda](https://lightpanda.io)
