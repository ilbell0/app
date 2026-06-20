import abbreviations from './abbreviations.json';
import arrowTactics from './arrowTactics.json';
import battleCards from './battleCards.json';
import careerPaths from './careerPaths.json';
import counterEngine from './counterEngine.json';
import counterQuick from './counterQuick.json';
import faq from './faq.json';
import formations from './formations.json';
import matchupMatrix from './matchupMatrix.json';
import metaTactics from './metaTactics.json';
import myPlaybook from './myPlaybook.json';
import playerRoles from './playerRoles.json';
import realTeams from './realTeams.json';
import seasonStories from './seasonStories.json';
import setPiece from './setPiece.json';
import specialAbilities from './specialAbilities.json';
import trainingGuide from './trainingGuide.json';

// schede didattiche dell'Academy: esclude Rapido e Matrice (sono counter,
// già conteggiati nella stat COUNTER) per non gonfiare il numero.
const academyItems =
  playerRoles.length +
  metaTactics.length +
  specialAbilities.length +
  trainingGuide.length +
  arrowTactics.length +
  realTeams.length +
  seasonStories.length +
  faq.length +
  abbreviations.length +
  careerPaths.length +
  myPlaybook.length +
  setPiece.length +
  battleCards.length;

export const APP_META = {
  datasets: 18,
  formations: formations.length,
  counters: counterEngine.length,
  quickCounters: counterQuick.length,
  matrixEntries: matchupMatrix.length,
  academySections: 15,
  academyItems,
  settingsBadge: 'OFFLINE · META 2026',
  footerLabel: 'DATASET OFFLINE',
  academySummary: {
    it: 'Ruoli · Frecce · Meta · Abilità · Allenam. · Squadre · Storie · FAQ · Rapido · Leggenda · Matrice · Percorsi · Mio Stile · Piazzati · Scontri',
    en: 'Roles · Arrows · Meta · Skills · Training · Teams · Stories · FAQ · Quick · Legend · Matrix · Paths · My Style · Set Piece · Battles',
  },
} as const;
