import abbreviations from './abbreviations.json';
import battleCards from './battleCards.json';
import careerPaths from './careerPaths.json';
import counterEngine from './counterEngine.json';
import faq from './faq.json';
import formationLab from './formationLab.json';
import formations from './formations.json';
import gameGuide from './gameGuide.json';
import mentors from './mentors.json';
import metaTactics from './metaTactics.json';
import myPlaybook from './myPlaybook.json';
import playerRoles from './playerRoles.json';
import positionGuide from './positionGuide.json';
import realTactics from './realTactics.json';
import realTeams from './realTeams.json';
import scoutTips from './scoutTips.json';
import setPiece from './setPiece.json';
import specialAbilities from './specialAbilities.json';
import trainingGuide from './trainingGuide.json';

// schede didattiche dell'Academy (i counter sono contati a parte).
// Deve coprire tutte le 16 SECTIONS di academy.tsx: se ne aggiungi una lì,
// aggiungila anche qui o il conteggio torna a disallinearsi.
const academyItems =
  playerRoles.length +
  positionGuide.length +
  metaTactics.length +
  specialAbilities.length +
  trainingGuide.length +
  faq.length +
  abbreviations.length +
  careerPaths.length +
  myPlaybook.length +
  setPiece.length +
  battleCards.length +
  gameGuide.length +
  formationLab.length +
  realTactics.length +
  realTeams.length +
  mentors.length;

export const APP_META = {
  datasets: 20,
  formations: formations.length,
  counters: counterEngine.length,
  scoutTips: scoutTips.length,
  academySections: 16,
  academyItems,
  settingsBadge: 'OFFLINE · META 2026',
  footerLabel: 'DATASET OFFLINE',
  academySummary: {
    it: 'Ruoli · Posizioni · Meta · Abilità · Allenam. · FAQ · Leggenda · Percorsi · Mio Stile · Piazzati · Scontri · Gestione · Lab Moduli · Calcio Reale · Squadre modello · Mentori',
    en: 'Roles · By Position · Meta · Skills · Training · FAQ · Legend · Paths · My Style · Set Piece · Battles · Club Guide · Formation Lab · Real Football · Team Models · Mentors',
  },
} as const;
