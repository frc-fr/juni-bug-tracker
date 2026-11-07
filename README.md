# juni-bug-tracker

Site statique de suivi des bugs (PR) de Junos OS et de Junos OS Evolved et de leurs corrections,
construit à partir des Release Notes publiques de Juniper Networks.

Ce projet est indépendant. Il n'est ni affilié à Juniper Networks ni à HPE, ni approuvé par eux.
Les informations sont fournies à titre indicatif : vérifiez toujours la documentation officielle.

## Fonctionnalités

- Recherche par numéro de PR ou mots-clés, par version et par matériel
- Junos OS et Junos OS Evolved, chacun avec ses propres données
- Mise en avant des branches supportées, sans masquer les autres
- Comparaison de deux versions : PR corrigés, nouveaux problèmes ouverts, changements de comportement
  (« What's Changed ») des notes traversées et chapitres de mise à niveau à lire
- Liste des modèles cités dans les PR
- Suivi des nouveautés, avec un flux RSS/Atom
- Interface en français et en anglais

Vos recherches et vos filtres restent dans votre navigateur : ils ne sont ni enregistrés ni transmis.

## Ce que disent les notes, et ce qu'elles ne disent pas

- Juniper publie une note par version R (25.4R1, 25.4R2…). Les versions de service (-S1, -S2…) n'ont
  pas de note propre. Quand une note distingue une version de service, elle est indiquée dans
  l'historique du PR.
- Chaque PR est rangé dans le chapitre d'une famille (MX Series, EX Series…). Le modèle précis n'est
  connu que lorsque le texte le cite. Le filtre matériel est donc inclusif : avec un modèle choisi, il
  garde les PR qui le citent et ceux de sa famille qui ne citent aucun modèle.
- Les avis de sécurité sont écartés et les références CVE retirées des descriptions.

## Sources

- Release Notes PDF sur `networkingdocs.hpe.com`, à une adresse prévisible par version. L'adresse
  change à partir de 26.2, première branche publiée sous HPE. Aucune page n'est parcourue : les PDF
  connus sont vérifiés par une requête HEAD, et une nouvelle version est cherchée aux quelques adresses
  qu'elle peut prendre (la version R suivante des trois dernières branches, la R1 des deux branches
  suivantes). Deux secondes séparent deux requêtes.
- `www.juniper.net` n'est jamais interrogé : son robots.txt interdit les robots. Une entrée
  `"manual": true` de `sources/manifest.json`, ajoutée à la main depuis une autre adresse, serait
  téléchargée une fois puis plus jamais interrogée. Aucune n'est nécessaire aujourd'hui.
- Versions de service (-S) : chacune a un article « Software Release Notification » (SRN) sur
  `supportportal.juniper.net`, dont le robots.txt autorise les robots. Le site renvoie vers cet article.
  Les articles sont découverts par le sitemap du portail, complété par une requête HEAD sur l'adresse
  prévisible de chaque numéro (200 s'il existe, 404 sinon). Leur contenu étant affiché en JavaScript, il
  est rendu par [Lightpanda](https://lightpanda.io), un navigateur sans interface. Seules les listes
  « Fixed issues » et « Known issues » sont lues ; une partie marquée « Confidential », les entrées de
  sécurité et les notes internes ne le sont jamais. Le champ « Resolved In » indique les autres versions
  corrigées. Un article n'est rendu que s'il est nouveau ou si sa date de modification dans le sitemap a
  changé. Le résultat est commité dans `data/` : vider le cache de la CI ne relance pas le rendu de tous les
  articles. Les numéros suivants ne sont vérifiés que sur la dernière version R de chaque branche.
- Dates de support : page [Junos OS Dates & Milestones](https://support.juniper.net/support/eol/software/junos/).
  Juniper n'y publie pas de table distincte pour Junos OS Evolved : le site applique les mêmes dates
  et le signale.

## Mise à jour

Le workflow GitHub Actions ne se lance pour l'instant qu'à la main (`workflow_dispatch`). Il collecte,
extrait, contrôle, puis publie le site sur GitHub Pages. Si un contrôle échoue, le site garde ses
dernières données valides.

## Développement

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
node --test tests/site/logic.test.js
```

Le rendu des articles SRN demande [Lightpanda](https://github.com/lightpanda-io/browser/releases)
(glibc 2.35 ou plus récente). La variable `JUNIBUGS_LIGHTPANDA` donne la commande à lancer si le binaire
n'est pas dans le `PATH`, par exemple un script qui le lance dans un conteneur.

Pour récupérer les documents puis prévisualiser le site :

```sh
.venv/bin/junibugs collect
.venv/bin/junibugs extract
.venv/bin/junibugs --base-url http://localhost:8010/ build
python3 -m http.server 8010 --directory dist
```

## Licence

Le code est distribué sous licence [GNU AGPL 3.0 ou ultérieure](LICENSE).

Cette licence ne couvre pas les contenus de tiers, notamment les textes issus de la documentation
Juniper. Juniper, Juniper Networks et Junos sont des marques de Juniper Networks, Inc.

## Contact

Outil créé et maintenu par [FR Consulting](https://fr-consulting.fr).
Pour toute demande : contact@fr-consulting.fr
