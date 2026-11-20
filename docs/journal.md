# Journal de bord de PinV, étape par étape

Ce journal raconte la construction de PinV dans l'ordre, en langage simple. Pour chaque étape : ce qu'on a fait, pourquoi, comment on l'a vérifié, ce qu'il faut en retenir, et ce qui a coincé. Les détails techniques sont dans [`architecture.md`](architecture.md).

---

## Étape 0. Le problème posé par le concours

**Le défi.** Jane Street et Tiny Tapeout demandent une puce capable d'« émuler » des protocoles, c'est-à-dire de parler les langues que les composants électroniques utilisent entre eux : UART, SPI, I2C au minimum. La puce doit pouvoir être reprogrammée pour en apprendre de nouvelles, sans être refabriquée.

**Les contraintes.** Une surface de 8 × 4 tuiles (environ 1 mm²), un procédé de fabrication IHP 130 nm (des transistors de 130 milliardièmes de mètre), une date limite au 18 janvier 2027, et un dossier qui doit contenir le circuit, les outils pour le programmer et un compte rendu.

**À retenir.** Un protocole, c'est une suite de 0 et de 1 envoyés sur des fils à des moments précis. La difficulté n'est pas de produire des 0 et des 1, c'est de les produire **au bon moment**.

---

## Étape 1. Le choix d'architecture : un petit processeur plutôt qu'un circuit par protocole

**Ce qu'on a fait.** Plutôt que de graver un circuit spécialisé par protocole, on met un petit processeur généraliste, auquel on ajoute quelques instructions pour piloter les broches et le temps. Chaque protocole devient un programme.

**Pourquoi.** C'est ce qui rend la puce flexible : un nouveau protocole, c'est un nouveau programme, pas une nouvelle puce. Et en prenant un processeur RISC-V standard, on peut utiliser le compilateur RISC-V existant au lieu d'écrire nos propres outils.

**À retenir.**
- **ISA** (jeu d'instructions) : la liste des ordres qu'un processeur comprend. RISC-V est une ISA ouverte, utilisable sans licence.
- **RV32E** : la version de RISC-V à 32 bits avec seulement 16 registres (au lieu de 32), pour gagner de la place.
- **Instructions compressées (le « C » de RV32EC)** : les instructions courantes tiennent sur 2 octets au lieu de 4, ce qui économise la mémoire.

---

## Étape 2. Réutiliser un processeur open source : PicoRV32

**Ce qu'on a fait.** On a repris PicoRV32, un cœur RISC-V écrit par Claire Wolf et utilisé dans de nombreux projets, sans le modifier, avec sa licence (ISC).

**Pourquoi.** Un processeur fait maison aurait demandé des semaines de vérification. PicoRV32 est éprouvé, petit, et surtout il possède une « porte d'extension », l'interface PCPI, prévue pour brancher des instructions maison sans toucher au cœur.

**Ce qu'on a comparé.** TinyQV, un autre cœur pensé pour Tiny Tapeout, garde son programme dans une mémoire externe qui occupe les 8 broches bidirectionnelles. Or l'I2C a justement besoin de ces broches. PicoRV32 avec une petite mémoire interne laisse toutes les broches libres.

**À retenir.** Réutiliser de l'open source est la norme, pas une faiblesse. La valeur est dans ce qu'on construit autour, et dans la façon dont on le prouve.

---

## Étape 3. L'unité broches et minutage : six instructions maison

**Ce qu'on a fait.** Un petit circuit (`src/pinv_io.v`) branché sur PCPI, qui ajoute six instructions :

| Instruction | Ce qu'elle fait |
|---|---|
| `PIN_OUT` | met certaines broches de sortie à 0 ou à 1 |
| `PIN_IN` | lit l'état des broches d'entrée |
| `PIN_DIR` | choisit si une broche bidirectionnelle émet ou écoute |
| `TIME` | lit le compteur de cycles (l'horloge interne) |
| `WAIT_UNTIL` | attend que le compteur atteigne une valeur précise |
| `WAIT_PIN` | attend qu'une broche prenne un niveau donné |

**L'idée clé : les échéances absolues.** Le processeur ne compte pas ses instructions pour savoir l'heure. Il se fixe un rendez-vous (« le prochain bit part au cycle 12 064 ») et attend ce rendez-vous avec `WAIT_UNTIL`. Peu importe le temps qu'ont pris les calculs entre deux bits : tant qu'ils ont fini avant le rendez-vous, le bit part pile à l'heure. Et comme chaque rendez-vous est calculé à partir du précédent, les erreurs ne s'accumulent jamais.

**À retenir.**
- **Cycle d'horloge** : le battement de cœur de la puce. À 40 MHz, il y en a 40 millions par seconde, soit un toutes les 25 nanosecondes.
- **Synchroniseur** : deux bascules en série sur chaque entrée, pour qu'un signal extérieur qui change au mauvais moment ne perturbe pas la puce.

---

## Étape 4. Le chargeur de programme

**Ce qu'on a fait.** Un petit récepteur SPI (`src/pinv_loader.v`). Quand la broche `LOAD` est haute, le processeur est mis en pause et le microcontrôleur de la carte de démo (un RP2350) envoie le programme bit par bit. Quand `LOAD` redescend, le processeur démarre à l'adresse 0.

**Pourquoi.** La puce perd sa mémoire quand elle est éteinte ou désélectionnée : il faut pouvoir la recharger à chaque fois.

**Ce qui a coincé.** Le premier test de chargement échouait : la mémoire restait vide. Le circuit était correct, c'était le test qui écrasait ses propres signaux, parce qu'il écrivait deux fois sur les mêmes broches au même instant de simulation. Leçon : quand un test échoue, il faut d'abord se demander si c'est le test ou le circuit qui se trompe.

---

## Étape 5. Les programmes de démonstration

**Ce qu'on a fait.** Trois programmes en assembleur RISC-V, dans `firmware/` :
- **UART** : envoie « Hello », puis renvoie chaque caractère reçu.
- **SPI** : lit l'identifiant d'une mémoire flash (commande `0x9F`) et l'affiche sur l'UART. Il fonctionne dans les 4 modes SPI.
- **I2C** : lit un registre d'un capteur, avec START répété, étirement d'horloge et détection d'un composant absent.

**À retenir.**
- **UART** : deux fils, pas d'horloge partagée. Les deux côtés se mettent d'accord sur une vitesse, d'où l'importance d'un minutage exact.
- **SPI** : le maître fournit l'horloge. Rapide et simple, avec quatre variantes selon le front d'horloge où l'on lit et où l'on écrit.
- **I2C** : deux fils partagés par plusieurs composants, en « drain ouvert » : personne ne force un 1, on ne fait que tirer à 0 ou relâcher, et une résistance remonte la ligne. Un composant lent peut retenir l'horloge pour faire attendre le maître (l'étirement d'horloge).

**Ce qui a coincé.** Le programme I2C dépassait les 512 octets de mémoire (612 octets). On l'a réorganisé autour d'une seule routine « un coup d'horloge », partagée par l'écriture, la lecture et les acquittements : il est passé à 456, puis 446 octets.

---

## Étape 6. La simulation et les faux appareils

**Ce qu'on a fait.** Avant de fabriquer, on fait tourner le circuit sur ordinateur (Icarus Verilog), piloté par des scripts Python (cocotb). En face de la puce, on a écrit de faux appareils : une fausse mémoire flash SPI, un faux capteur I2C qui sait retenir l'horloge, un faux terminal UART. 8 tests vérifient chaque échange, au cycle près.

**Comment on l'a montré.** La page « PinV en simulation » affiche les vrais signaux de ces tests, avec les octets décodés. On peut aussi ouvrir le fichier `test/tb.fst` dans Surfer ou GTKWave pour voir tous les signaux internes.

**À retenir.** Une simulation teste les cas qu'on a pensé à écrire. Elle ne dit rien des autres. C'est la limite que les étapes 8 et 9 viennent combler.

---

## Étape 7. La fabrication virtuelle et le minutage physique

**Ce qu'on a fait.** À chaque envoi sur GitHub, l'outil de Tiny Tapeout (LibreLane) transforme le code en dessin de puce : il choisit les portes logiques, les place, trace les fils, puis vérifie les règles de fabrication et le minutage.

**Ce qui a coincé, deux fois.**
1. À 50 MHz, le dessin était complet (43 % de la surface), mais certains signaux arrivaient trop tard dans le cas le plus défavorable (puce lente, 1,08 V, 125 °C). L'outil avait ajouté environ 5 200 petits composants pour corriger d'autres contraintes autour de la mémoire, ce qui a rallongé certains chemins.
2. On a voulu passer à 40 MHz en modifiant `info.yaml`, mais ce fichier ne sert qu'à la documentation. La vraie contrainte se règle dans `src/config.json` (`CLOCK_PERIOD`, en nanosecondes). Le run suivant visait donc toujours 50 MHz. Corrigé à 25 ns.

**À retenir.**
- **Temps de setup** : un signal doit arriver un peu avant le battement d'horloge suivant. Si le chemin est trop long, il arrive trop tard.
- **Coins de fonctionnement** : on vérifie la puce dans les pires conditions de tension et de température, pas seulement dans les conditions idéales.
- **GDS** : le fichier final qui décrit chaque couche de la puce, celui qu'on envoie à l'usine.

---

## Étape 8. Le vérificateur de minutage : prouver chaque programme

**Le problème.** L'idée des rendez-vous (étape 3) ne marche que si le code entre deux rendez-vous finit toujours à temps. Un test le vérifie pour les chemins qu'il emprunte. Mais un programme a de nombreux chemins (conditions, boucles, appels de fonctions), et il suffit d'un seul trop lent pour envoyer un bit faux.

**Ce qu'on a fait.** Un outil, `tools/pinv_check.py`, qui lit le programme compilé, reconstruit tous ses chemins possibles et calcule, pour chaque rendez-vous, le pire temps pour l'atteindre. Chaque programme déclare son budget avec `PINV_BUDGET(cycles)`. Si un seul chemin dépasse, la compilation échoue et aucun binaire n'est produit.

**Comment on sait que ses calculs sont justes.**
1. On a chronométré chaque instruction sur la simulation du circuit lui-même, avec environ 170 mini-programmes. Par exemple : 3 cycles pour une addition, 5 pour une lecture mémoire, un cycle de plus pour une instruction mal alignée, et 4 + k/4 + k mod 4 cycles pour un décalage de k bits.
2. On a ajouté aux tests un détecteur qui mesure chaque rendez-vous dans la simulation. Au budget minimal que l'outil annonce, aucun rendez-vous n'est raté ; avec un cycle de moins, un rendez-vous l'est. Et ce, pour les trois protocoles.

**Ce qu'il a trouvé.** La démo SPI demandait des demi-périodes de 48 cycles, alors qu'un chemin de sa boucle en prend 77. Les tests passaient quand même, parce qu'en SPI un rendez-vous raté ralentit l'horloge sans fausser les données. La puce aurait tourné moins vite que prévu sans que personne le voie.

**À retenir.** C'est une **analyse statique du pire temps d'exécution** (WCET). La même famille de techniques sert dans l'aéronautique et l'automobile pour garantir qu'un calculateur répond toujours à temps.

---

## Étape 9. La preuve formelle du matériel

**Le problème.** Le vérificateur de l'étape 8 suppose que le circuit tient ses promesses, par exemple que `WAIT_UNTIL` libère le processeur exactement au bon cycle. Les tests le montrent sur quelques cas. Il faut le démontrer pour tous.

**Ce qu'on a fait.** Avec SymbiYosys et le solveur Z3, on a écrit les promesses du circuit sous forme de propriétés mathématiques (`formal/`), et l'outil a démontré qu'elles sont vraies dans tous les états possibles du circuit, quelles que soient les entrées.

| Module | Ce qui est prouvé |
|---|---|
| Unité broches et minutage | le compteur avance d'exactement 1 par cycle ; chaque instruction reçoit une seule réponse ; `WAIT_UNTIL` libère exactement au cycle de l'échéance quand elle est dans le futur (zéro gigue) ; `PIN_OUT` ne modifie que les broches demandées, un cycle après, et rien d'autre ne touche aux sorties ; seul `PIN_DIR` change le sens des broches |
| Chargeur | un octet n'est écrit qu'en mode chargement, après son 8e bit ; chaque chargement repart de l'adresse 0 ; les adresses avancent d'exactement 1 par octet ; l'octet écrit est bien celui reçu |
| Module principal | le chargeur n'écrit jamais en mémoire pendant qu'un programme tourne ; le processeur est en pause tant que `LOAD` est haut, et repart dès qu'il redescend |

**Comment on sait que la preuve n'est pas vide.**
- Des **covers** montrent que les situations intéressantes sont bien atteignables. Une preuve fondée sur des hypothèses contradictoires « prouverait » n'importe quoi.
- Des **mutations** : on a introduit volontairement trois bugs dans le circuit (libérer un cycle trop tôt, ignorer le masque de `PIN_OUT`, répondre deux fois). La preuve a échoué à chaque fois et a pointé la bonne propriété.

**Une astuce honnête.** Pour le module principal, on a remplacé le processeur par une « boîte noire » dont les sorties peuvent prendre n'importe quelle valeur à chaque cycle. Si les propriétés tiennent face à un processeur qui fait n'importe quoi (un bug, un programme malveillant), elles tiennent pour le vrai.

**À retenir.**
- **Test** : « ça marche sur les cas essayés ». **Preuve formelle** : « ça marche dans tous les cas, démonstration à l'appui ».
- **Induction** : on prouve que la propriété est vraie au départ, puis que si elle est vraie à un instant, elle l'est à l'instant suivant. Elle est donc vraie pour toujours.
- Les deux étapes se complètent. La preuve formelle garantit le contrat du matériel ; le vérificateur de minutage garantit que chaque programme respecte ce contrat. Ensemble, elles donnent une garantie de bout en bout sur le moment où chaque bit sort.

---

## Étape 10. La vitesse : des instructions « fusionnées »

**Le problème.** Envoyer un bit demandait quatre instructions : attendre l'échéance, changer la broche, décaler la donnée, avancer l'échéance. Chacune passe par la porte d'extension de PicoRV32, qui coûte 6 cycles. Résultat : 44 cycles par bit au minimum, quand un concurrent inspiré des PIO du RP2040 change une broche à chaque cycle.

**Ce qu'on a fait.** L'unité garde désormais sa propre échéance et son propre pas. Une seule instruction, `SHIFT_OUT`, attend l'échéance, sort le bit, décale la donnée et avance l'échéance. Même chose en réception avec `SHIFT_IN`, et `WAIT_TICK` pour une simple attente périodique.

**Le résultat, mesuré et prouvé.**
- Le vérificateur prouve maintenant l'UART à **18 cycles par bit**, contre 44 : 2,4 fois plus rapide, soit environ 2,2 Mbaud à 40 MHz.
- Sur le circuit simulé, aucune échéance n'est ratée à 18 cycles ; à 17, une l'est, d'exactement 1 cycle, à l'instruction que le vérificateur avait désignée.
- La preuve formelle couvre les nouvelles instructions. Zéro gigue, l'échéance avance d'exactement un pas, et le bit sort sur la bonne broche et nulle part ailleurs. Trois nouveaux bugs volontaires ont tous été attrapés, chacun avec un contre-exemple concret.

**Ce qui a coincé.**
- Le vérificateur a montré que le goulot n'était plus l'émission mais la préparation de la réception, entre le bit de start et la première lecture. On a déplacé ces calculs avant l'attente du bit de start.
- À 16 cycles par bit, une constante plus petite tient dans une instruction plus courte. Le code se décale et l'alignement change, ce qui coûte 2 cycles. Seule l'analyse du vrai binaire pouvait le voir.

**À retenir.** Accélérer, c'est d'abord mesurer où part le temps. Ici, le vérificateur de minutage sert aussi d'outil d'optimisation : il pointe le segment le plus lent.

---

## Étape 11. La cyber, prouvée

**L'idée.** La preuve formelle ne sert pas qu'à vérifier que le circuit fonctionne. Elle peut aussi démontrer qu'il résiste à certaines attaques, à condition de dire précisément lesquelles.

**Trois protections ajoutées, chacune prouvée :**
1. **Attentes bornées (contre le déni de service).** Avant, un composant malveillant qui retenait une ligne I2C bloquait la puce pour toujours. Maintenant, `SET_LIMIT` fixe une durée maximale d'attente. La preuve démontre qu'aucune attente limitée ne la dépasse, quoi qu'il arrive sur les broches. Un test simule un composant qui bloque l'horloge pour toujours : la puce termine et affiche `#`.
2. **Le verrou du programme (contre le remplacement ou l'arrêt).** Après `LOCK`, la broche de chargement est ignorée jusqu'au redémarrage. La preuve tient même face à un processeur qui ferait n'importe quoi : le chargeur n'écrit plus, et le processeur ne peut plus être arrêté de l'extérieur.
3. **Non-interférence du minutage (contre l'espionnage par le temps).** On fait tourner deux copies du circuit avec les mêmes instructions mais des données différentes, et on prouve qu'elles répondent toujours aux mêmes cycles. L'instant où un bit sort ne dépend donc pas de sa valeur : un attaquant qui chronomètre les signaux n'apprend rien.

**Comment on sait que ça tient.** Quatre bugs volontaires (une limite ignorée, un abandon un cycle trop tard, un minutage qui dépend de la donnée, un verrou contourné) ont chacun été attrapés avec un contre-exemple concret.

**Ce qui a coincé.**
- Le solveur Z3 bloquait, même sans aucune propriété à prouver. En comparant l'ancienne et la nouvelle version du circuit, on a isolé la logique de délai maximal. Le vrai coupable était cette version ancienne de Z3 : avec le solveur Yices, chaque preuve passe en une seconde environ.
- Une propriété vraie ne passait pas l'induction, faute d'information. Il a fallu l'énoncer plus précisément : une attente sur broche n'existe que pendant une instruction `WAIT_PIN` en cours.
- Le vérificateur de minutage a encore refusé un binaire : trois instructions ajoutées avaient décalé le code, et le segment le plus lent de l'I2C dépassait son budget de 2 cycles.

**Ce que la preuve ne couvre pas, et qu'il faut écrire dans le dossier.** Les attaques physiques (perturbation de tension ou d'horloge, laser, mesure de la consommation), le processeur PicoRV32 lui-même (réutilisé tel quel), les propriétés qu'on n'a pas pensé à écrire, et les pertes au niveau du protocole.

---

## Étape 12. La simulation sur portes réelles révèle un vrai bug

**Le symptôme.** La fabrication virtuelle passait à 40 MHz, mais la simulation sur le circuit tel qu'il sera gravé (les portes IHP réelles) ne produisait rien : pas un octet, sur aucun protocole.

**L'enquête.**
1. Une simulation avec des portes génériques passait. Le problème venait donc des modèles de cellules IHP.
2. Avec les vrais modèles IHP, tout restait indéterminé (`X`). Raison : ces modèles ne pilotent leurs entrées qu'à travers des contraintes de timing, que notre version d'Icarus ne gère pas. On a fabriqué une copie fonctionnelle des modèles, où chaque signal « retardé » est relié directement à son origine.
3. Résultat : les sorties passaient bien à 0 à la remise à zéro, puis redevenaient indéterminées dès le démarrage. En suivant les signaux du processeur cycle par cycle, la cause est apparue.

**La cause.** Juste après la remise à zéro, avant tout chargement, le processeur démarrait et exécutait le contenu de la mémoire vide. En simulation, ce contenu indéterminé contaminait le verrou, qui contaminait la remise à zéro du processeur, et la puce ne s'en remettait jamais. Sur une vraie puce, le contenu est aléatoire au démarrage. S'il tombait par hasard sur l'instruction `LOCK`, la puce devenait impossible à programmer jusqu'au redémarrage suivant.

**La correction.** Le processeur reste à l'arrêt tant qu'aucun programme n'a été chargé. En ajoutant la propriété correspondante à la preuve formelle, celle-ci a trouvé un second cas limite : une remise à zéro d'un seul cycle, au moment précis d'un `LOCK`, pouvait verrouiller une puce sans programme. Corrigé à son tour : le verrou n'est accepté que d'un programme réellement en marche.

**À retenir.** Chaque niveau de vérification attrape des choses que les autres ne voient pas. Les tests sur le code supposent que tout registre a une valeur ; le circuit réel ne fait pas ce cadeau. C'est aussi pour ça que le règlement recommande la simulation sur portes.

---

## Étape 13. La fabrication virtuelle bloquée par des plots d'entrée/sortie

**Le symptôme.** Après la correction de l'étape 12, la fabrication virtuelle (GDS) échouait au placement : « l'instance _45354_ n'est pas placée ». Changer la densité de placement ou désactiver le placement guidé par le routage ne changeait rien : la même instance bloquait toujours.

**La cause.** En comparant la liste des cellules avec celle du dernier run réussi, deux cellules inattendues sont apparues : des plots de sortie IHP (`IOPadOut16mA`). Ce sont les gros blocs de connexion placés normalement au bord de la puce, d'environ 14 400 µm² chacun. L'outil de synthèse (ABC) les avait choisis comme amplificateurs pour deux signaux très chargés, parce qu'ils figurent dans la bibliothèque qu'on lui donne. Aucun ne peut tenir dans une tuile.

**La correction.** Une ligne dans `src/config.json` : `"EXTRA_EXCLUDED_CELLS": ["sg13cmos5l_IOPad*"]`, qui interdit ces cellules à la synthèse. Résultat : la fabrication virtuelle passe (2 h 24), la simulation sur portes réelles aussi (UART, SPI, I2C, verrou), avec la correction de l'étape 12 incluse.

**À retenir.** Quand une erreur résiste à tous les réglages, il faut chercher ce qui a changé entre le dernier run réussi et le premier en échec, ici la liste des cellules, au lieu de continuer à tourner des boutons.

---

## Étape 14. Trois ajouts : impulsions exactes, état de repos, pare-feu SPI

**1. Le sérialiseur de formes d'onde (`PULSE`).** Certains protocoles codent un bit par la durée d'une impulsion, comme les LED WS2812 : un 0 est haut 0,4 µs, un 1 est haut 0,8 µs, sur une période de 1,25 µs. Avec les instructions existantes, il fallait deux fronts logiciels par bit. `PULSE` place les deux fronts en matériel : le front montant à l'échéance, le front descendant exactement t cycles plus tard, avec t choisi par le bit (`SET_WAVE` règle les deux durées). Le processeur n'envoie qu'une instruction par bit.

- Démo `ws2812.S` : 4 LED, couleurs qui tournent. 128 octets.
- Le vérificateur de minutage prouve le programme pour toute période d'au moins 39 cycles (un peu plus de 1 Mbit/s à 40 MHz). Le WS2812 demande 50 cycles.
- En simulation, chaque impulsion dure exactement 16 ou 32 cycles et chaque période exactement 50.

**2. L'état de repos (`SET_IDLE`).** Avant, toutes les sorties passaient à 0 pendant un rechargement de programme. Pour une ligne UART, c'est un faux bit de départ. Pour un chip select actif à l'état bas, ça sélectionne la puce voisine. Maintenant, le programme choisit l'état des sorties pendant un rechargement. Seule une vraie remise à zéro de la puce l'efface.

**3. Le pare-feu de bus SPI (`spi_firewall.S`).** PinV se place entre un microcontrôleur et la mémoire flash qui contient son firmware. Les lectures passent. Les écritures et les effacements sont bloqués avant que la flash ne voie un seul bit, puis journalisés sur l'UART. Le programme verrouille la puce (`LOCK`), garde la flash désélectionnée pendant un rechargement (`SET_IDLE`) et borne toutes ses attentes (`SET_LIMIT`). Un hôte compromis ne peut donc ni écrire dans la flash, ni retirer le pare-feu, ni le bloquer. Limite assumée : le bus est recopié en logiciel, donc l'hôte doit rester sous 33 kHz environ.

**Les preuves.** Nouvelles propriétés formelles : la largeur exacte de chaque impulsion, le front descendant qui n'est jamais perdu quelle que soit l'instruction en cours, l'état de repos appliqué à chaque rechargement. Cinq bugs injectés exprès sont tous détectés, avec un contre-exemple concret.

**Ce que la preuve a attrapé en chemin.** Une de mes propriétés était fausse sans le dire : à cause de la priorité des opérateurs en Verilog (`==` passe avant `|`), elle était toujours vraie. Le test par mutation l'a révélé, parce qu'un bug injecté passait. Corrigé. Deux autres trouvailles : le moniteur des tests prenait `LOCK` et `SET_IDLE` pour des attentes, et le vérificateur de minutage refusait un programme qui n'appelle pas toutes les routines UART. Corrigés aussi.

**À retenir.** Une preuve qui passe ne vaut que si elle peut échouer. Injecter des bugs exprès est le seul moyen de le vérifier.

---

## Ce qui reste à faire

1. Relire le compte rendu pour le jury (`docs/writeup.md`).
2. Soumettre avant le 18 janvier 2027.
