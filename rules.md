---
type: Project Rules
title: Règles de juni-bug-tracker
description: Règles communes aux bug trackers et particularités de Junos OS et Junos OS Evolved.
resource: https://github.com/frc-fr/juni-bug-tracker
tags: [rules, junos, juniper, hpe, bug-tracker]
timestamp: 2026-11-15T20:00:00+01:00
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
  - `extract` : lit les documents en cache et écrit le rapport de traitement ; n'échoue que sous le seuil de publication.
  - `build` : croise les données et génère `dist/`.
  - `check` : échoue s'il reste un document non compris, suspect ou inaccessible, ou une source en échec.
- Modules communs : `collect`, `parser`, `extract`, `normalize` (matériel), `build`, `feed`, `report` (identique partout), `cli`.
- Modules propres au fournisseur (dates de support, fin de vie du matériel, sources annexes) : nommés d'après ce qu'ils lisent, décrits dans ses particularités.

### Répertoires

- `sources/` : état des sources (adresses, ETag, lastmod, dates de support). Commité.
- `.cache/` : documents bruts. Non versionné, gardé par le cache de la CI.
- `data/extracted/` : un JSON par document, une ligne par bug pour des diffs lisibles. Commité.
- `data/changes.json` : journal des nouveautés. Absent au départ : la première extraction sert de référence.
- `data/report.json` : rapport du dernier traitement, une ligne par document. Commité.
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
- Un document non compris est publié pour ce qui est compris ; un document qui ne se lit plus ou perd plus de la moitié de ses bugs garde sa dernière lecture valide.
- La mise à jour ne s'arrête que si moins de 75 % des documents sont lus : le site garde alors sa version précédente plutôt qu'un site vide.
- Une source annexe (dates de support…) en échec garde ses dernières valeurs.
- Le navigateur ne contacte jamais de service tiers.

## Contenu

- Objet : bugs connus et bugs corrigés. Jamais la sécurité.
- Entrées de sécurité écartées, références CVE retirées des descriptions.
- Chaque fait renvoie à la page officielle exacte qui le porte.
- Textes des bugs laissés en anglais, tels que publiés.
- Statuts déduits des notes, jamais inventés ; « Inconnu » expliqué et masqué par défaut.
- Un modèle cité ne veut pas dire « seul ce modèle est touché ». Filtre matériel inclusif : avec un modèle choisi, bugs qui le citent, ceux qui ne citent que sa famille et ceux qui ne citent aucun matériel.
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

## État du traitement

- Page `etat.html`, liée en bas de page sur la ligne des mentions légales, en petit. Aucune pastille ailleurs.
- Même page, même `status.js`, même style et mêmes textes dans les cinq sites ; seuls les codes de règle propres au fournisseur diffèrent.
- Statuts : lu, écarté par règle, suspect, non compris, inaccessible. Seuls les quatre derniers sont détaillés.
- Chaque identifiant de bug listé par l'éditeur finit lu, écarté par règle ou non compris ; sinon il est « non compté » et le document est suspect.
- Chaque constat donne la page exacte de l'éditeur, l'endroit (section, légende), le nombre de bugs, quelques identifiants et la date depuis laquelle il dure.
- Contenus non exploités : sections jamais lues, identifiants cités hors des listes de bugs.
- Sources : chaque étape de la collecte, son dernier succès et ses erreurs.
- Spécification détaillée : `bug-trackers-status-spec.md` (hors dépôts).

## Matériel et nouveautés

- Onglet Matériel : pastilles « Tous », « Aucune fin annoncée », « Fin de vie annoncée », « Plus maintenu », dans cet ordre.
- « Plus maintenu » : le fournisseur ne publie plus de version pour ce modèle (dernière version avant la dernière branche, fin de maintenance logicielle ou fin de support passée). La note de l'onglet dit laquelle.
- Colonnes : Modèle, Première version, Dernière version, Statut <logiciel>, Version recommandée, Fin de support. Mêmes libellés partout.
- Filtre « Modèle ou famille » ; un modèle qu'aucun bug ne cite renvoie vers sa famille.
- Statut tiré d'une source officielle du fournisseur : il dit, sans le deviner, si le matériel est encore maintenu.
- Fin de vie annoncée par référence : variantes affichées séparément, pièces détachées et modules écartés.
- Pas de source : « Aucune fin annoncée », jamais « supporté ».
- Version recommandée seulement si le fournisseur la publie sans compte ; sinon la colonne est absente, et la note dit pourquoi. Libellé fidèle au mot du fournisseur (« suggérée », « actuelles ») : ne pas affirmer plus que lui.
- Rechercher : un modèle choisi affiche ce que le fournisseur dit de lui (statut, version recommandée, fin de support).
- Quoi de neuf : cartes « Dernière version publiée », « Dernière note mise à jour », puis la version recommandée du fournisseur si elle existe, avec son mot (« Recommandée par Fortinet », « Suggérée par Juniper »).

## Design

- Même structure et mêmes jetons de couleur dans les cinq sites.
- Couleur du fournisseur en touche seulement : bordure haute et nom du produit.
- Contraste professionnel, rien qui « pique les yeux ».
- Cohérence entre pages : mêmes pastilles partout, pas de tuiles géantes.

## Publication

- Cron du lundi au vendredi : 9 h 15, 14 h 15, 19 h 00, Europe/Paris.
- Horaire décrit dans `sources/schedule.yml` et affiché sur le site, qui le lit au build.
- Workflow GitHub sans déclencheur `schedule` (retardé ou oublié par GitHub) : lancé par `workflow_dispatch`.
- Ordre : tests, collecte, extraction, commit des données, build, GitHub Pages, puis tests sur le corpus réel et `check` : un passage rouge demande d'adapter le code, le site est déjà à jour.
- Flux RSS/Atom des nouveautés.
- CSP stricte : aucun script, style ou service tiers.

## Mentions et licence

- Outil créé et maintenu par FR Consulting ; contact@fr-consulting.fr ; lien vers fr-consulting.fr.
- Site indépendant, non affilié au fournisseur. Jamais « approuvé par ».
- Mentions légales FR et EN, avec la liste des services et composants tiers. Lien « État du traitement » sur la même ligne.
- Code sous AGPL 3.0 ou ultérieure ; contenus du fournisseur exclus.
- README générique : rien de sensible ni de personnel.
- Plan unique des README : Fonctionnalités, Ce que disent les notes, Sources, Mise à jour, Liens utiles chez <fournisseur>, Développement, Licence, Contact.
- Plan unique des particularités de ce fichier : Logiciels (si plusieurs), Versions, Sources, Extraction, Matériel, Affichage, Citations.

# Particularités Junos

## Deux logiciels

- Junos OS et Junos OS Evolved : sélecteur « Logiciel », données séparées.
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
- Articles rendus par Lightpanda (JavaScript).
- Article rendu seulement s'il est nouveau ou si son lastmod a changé.
- PDF de SRN déposés à la main dans `.cache/srn-attachments` : lus après l'article.
- Dates de support : page Junos OS Dates & Milestones. Pas de table Evolved : mêmes dates, réserve affichée.

## Extraction

- PDF des notes : chaque PR est lu dans le chapitre de sa famille.
- SRN : seulement « Fixed issues » et « Known issues ».
- Partie « Confidential », entrées de sécurité et notes internes jamais lues.
- SRN illisible (vide, pièce jointe, texte d'une autre version) : raison affichée, statuts partiels.
- Règles propres à Juniper : `no_family` (PDF sans chapitre de famille connue), `family_unknown` (problèmes d'un chapitre sans famille connue), `no_issue` (aucun problème lu), `no_revision_history` (date de publication introuvable), `row_unknown` (ligne de SRN impossible à découper), `confidential` (partie « Confidential », sans identifiants puisqu'elle n'est pas lue), `srn_empty`, `srn_attachment`, `srn_other_release` (SRN illisible, sans copie PDF).
- PR listé dans un PDF : tout numéro `PR…` d'une section de problèmes (« Open Issues », « Resolved Issues », « Known Limitations », ou tout titre parlant d'issues, bugs, limitations), même sous un titre inconnu. « Page » : le PDF à la page du PR ; « où » : famille / section.
- PR listé dans un SRN : ligne de tableau dont la première cellule commence par un numéro, lien ou pas ; hors partie « Confidential ». « Page » : l'article ; « où » : titre de la liste.
- PR cités dans « What's Changed » ou dans le texte d'un article : contenus non exploités, pas listés.
- Cadre exclu des sections non lues : couverture, table des matières, introduction, support, retour sur la documentation (PDF) ; type d'alerte, produits, téléchargement, « Solution », pied de page (SRN).

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
- Lien vers l'article SRN, pas vers le PDF.
- Sévérité Juniper affichée, avec lien vers les définitions Juniper en pied de page.
- « What's Changed » des notes traversées dans la comparaison.
- Couleur de marque : vert Juniper.

# Citations

[1] [SRN Definitions of Severity](https://supportportal.juniper.net/s/article/SRN-Definitions-of-Severity)
[2] [Junos OS Dates & Milestones](https://support.juniper.net/support/eol/software/junos/)
[3] [Lightpanda](https://lightpanda.io)
