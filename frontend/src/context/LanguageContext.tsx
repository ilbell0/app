import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

type Language = 'en' | 'it';

interface Translations {
  [key: string]: {
    en: string;
    it: string;
  };
}

const translations: Translations = {
  // Navigation
  home: { en: 'Home', it: 'Home' },
  formations: { en: 'Formations', it: 'Formazioni' },
  counters: { en: 'Counters', it: 'Contro' },
  scout: { en: 'Scout', it: 'Scout' },
  aiTactics: { en: 'AI Tactics', it: 'Tattiche AI' },
  profile: { en: 'Profile', it: 'Profilo' },
  
  // Login
  welcome: { en: 'Welcome to', it: 'Benvenuto su' },
  appName: { en: 'Top Eleven Tactics', it: 'Top Eleven Tactics' },
  appDescription: { en: 'Your ultimate tactical companion for Top Eleven football manager game', it: 'Il tuo compagno tattico definitivo per Top Eleven' },
  loginWithGoogle: { en: 'Login with Google', it: 'Accedi con Google' },
  continueAsGuest: { en: 'Continue as Guest', it: 'Continua come Ospite' },
  
  // Home
  welcomeBack: { en: 'Welcome back', it: 'Bentornato' },
  quickAccess: { en: 'Quick Access', it: 'Accesso Rapido' },
  viewFormations: { en: 'View Formations', it: 'Vedi Formazioni' },
  counterTactics: { en: 'Counter Tactics', it: 'Contro-Tattiche' },
  scoutTips: { en: 'Scout Tips', it: 'Consigli Scout' },
  askAI: { en: 'Ask AI', it: 'Chiedi all\'AI' },
  latestTips: { en: 'Latest Tips', it: 'Ultimi Consigli' },
  
  // Formations
  allFormations: { en: 'All Formations', it: 'Tutte le Formazioni' },
  strengths: { en: 'Strengths', it: 'Punti di Forza' },
  weaknesses: { en: 'Weaknesses', it: 'Debolezze' },
  positions: { en: 'Positions', it: 'Posizioni' },
  addToFavorites: { en: 'Add to Favorites', it: 'Aggiungi ai Preferiti' },
  removeFromFavorites: { en: 'Remove from Favorites', it: 'Rimuovi dai Preferiti' },
  
  // Counter Tactics
  selectFormation: { en: 'Select opponent formation', it: 'Seleziona formazione avversaria' },
  bestCounters: { en: 'Best Counter Formations', it: 'Migliori Formazioni Contro' },
  reason: { en: 'Why it works', it: 'Perché funziona' },
  
  // Scout
  categories: { en: 'Categories', it: 'Categorie' },
  defense: { en: 'Defense', it: 'Difesa' },
  midfield: { en: 'Midfield', it: 'Centrocampo' },
  attack: { en: 'Attack', it: 'Attacco' },
  training: { en: 'Training', it: 'Allenamento' },
  budget: { en: 'Budget', it: 'Budget' },
  tactics: { en: 'Tactics', it: 'Tattiche' },
  
  // AI Chat
  aiAssistant: { en: 'AI Tactical Assistant', it: 'Assistente Tattico AI' },
  typeMessage: { en: 'Ask about tactics, formations, players...', it: 'Chiedi di tattiche, formazioni, giocatori...' },
  send: { en: 'Send', it: 'Invia' },
  clearHistory: { en: 'Clear History', it: 'Cancella Cronologia' },
  loginRequired: { en: 'Login required to use AI assistant', it: 'Accedi per usare l\'assistente AI' },
  
  // Profile
  settings: { en: 'Settings', it: 'Impostazioni' },
  language: { en: 'Language', it: 'Lingua' },
  english: { en: 'English', it: 'Inglese' },
  italian: { en: 'Italian', it: 'Italiano' },
  favorites: { en: 'My Favorites', it: 'I Miei Preferiti' },
  logout: { en: 'Logout', it: 'Esci' },
  guest: { en: 'Guest', it: 'Ospite' },
  
  // Common
  loading: { en: 'Loading...', it: 'Caricamento...' },
  error: { en: 'Error', it: 'Errore' },
  retry: { en: 'Retry', it: 'Riprova' },
  back: { en: 'Back', it: 'Indietro' },
  noData: { en: 'No data available', it: 'Nessun dato disponibile' },
};

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string) => string;
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};

interface LanguageProviderProps {
  children: ReactNode;
}

export const LanguageProvider: React.FC<LanguageProviderProps> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>('it');

  useEffect(() => {
    loadLanguage();
  }, []);

  const loadLanguage = async () => {
    try {
      const savedLang = await AsyncStorage.getItem('language');
      if (savedLang === 'en' || savedLang === 'it') {
        setLanguageState(savedLang);
      }
    } catch (error) {
      console.error('Error loading language:', error);
    }
  };

  const setLanguage = async (lang: Language) => {
    try {
      await AsyncStorage.setItem('language', lang);
      setLanguageState(lang);
    } catch (error) {
      console.error('Error saving language:', error);
    }
  };

  const t = (key: string): string => {
    const translation = translations[key];
    if (!translation) {
      console.warn(`Translation missing for key: ${key}`);
      return key;
    }
    return translation[language];
  };

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
};
