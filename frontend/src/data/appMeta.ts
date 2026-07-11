import abbreviations from './abbreviations.json';
import battleCards from './battleCards.json';
import careerPaths from './careerPaths.json';
import counterEngine from './counterEngine.json';
import faq from './faq.json';
import formations from './formations.json';
import gameGuide from './gameGuide.json';
import metaTactics from './metaTactics.json';
import myPlaybook from './myPlaybook.json';
import playerRoles from './playerRoles.json';
import realTeams from './realTeams.json';
import scoutTips from './scoutTips.json';
import seasonStories from './seasonStories.json';
import setPiece from './setPiece.json';
import specialAbilities from './specialAbilities.json';
import trainingGuide from './trainingGuide.json';

// schede didattiche dell'Academy (i counter sono contati a parte)
const academyItems =
  playerRoles.length +
  metaTactics.length +
  specialAbilities.length +
  trainingGuide.length +
  realTeams.length +
  seasonStories.length +
  faq.length +
  abbreviations.length +
  careerPaths.length +
  myPlaybook.length +
  setPiece.length +
  battleCards.length +
  gameGuide.length;

export const APP_META = {
  datasets: 19,
  formations: formations.length,
  counters: counterEngine.length,
  scoutTips: scoutTips.length,
  academySections: 13,
  academyItems,
  settingsBadge: 'OFFLINE · META 2026',
  footerLabel: 'DATASET OFFLINE',
  academySummary: {
    it: 'Ruoli · Meta · Abilità · Allenam. · Squadre · Storie · FAQ · Leggenda · Percorsi · Mio Stile · Piazzati · Scontri · Gestione',
    en: 'Roles · Meta · Skills · Training · Teams · Stories · FAQ · Legend · Paths · My Style · Set Piece · Battles · Club Guide',
  },
} as const;
