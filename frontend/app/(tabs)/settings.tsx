import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';

export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const { language, setLanguage, t } = useLanguage();

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>
          {language === 'it' ? 'Impostazioni' : 'Settings'}
        </Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {/* App Info */}
        <View style={styles.appInfoCard}>
          <View style={styles.appIcon}>
            <Ionicons name="football" size={40} color="#10b981" />
          </View>
          <Text style={styles.appName}>Top Eleven Tactics Wiki</Text>
          <Text style={styles.appVersion}>v2.0 - META 2026</Text>
          <Text style={styles.appDescription}>
            {language === 'it' 
              ? 'Il manuale tattico definitivo per Top Eleven'
              : 'The ultimate tactical manual for Top Eleven'}
          </Text>
        </View>

        {/* Language Section */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Ionicons name="language" size={20} color="#10b981" />
            <Text style={styles.sectionTitle}>
              {language === 'it' ? 'Lingua' : 'Language'}
            </Text>
          </View>
          
          <View style={styles.languageOptions}>
            <TouchableOpacity
              style={[
                styles.languageButton,
                language === 'it' && styles.languageButtonActive,
              ]}
              onPress={() => setLanguage('it')}
            >
              <Text style={styles.flagEmoji}>🇮🇹</Text>
              <Text style={[
                styles.languageText,
                language === 'it' && styles.languageTextActive,
              ]}>
                Italiano
              </Text>
              {language === 'it' && (
                <Ionicons name="checkmark-circle" size={20} color="#10b981" />
              )}
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[
                styles.languageButton,
                language === 'en' && styles.languageButtonActive,
              ]}
              onPress={() => setLanguage('en')}
            >
              <Text style={styles.flagEmoji}>🇬🇧</Text>
              <Text style={[
                styles.languageText,
                language === 'en' && styles.languageTextActive,
              ]}>
                English
              </Text>
              {language === 'en' && (
                <Ionicons name="checkmark-circle" size={20} color="#10b981" />
              )}
            </TouchableOpacity>
          </View>
        </View>

        {/* Features Section */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Ionicons name="list" size={20} color="#8b5cf6" />
            <Text style={styles.sectionTitle}>
              {language === 'it' ? 'Contenuti' : 'Contents'}
            </Text>
          </View>
          
          <View style={styles.featuresList}>
            <View style={styles.featureItem}>
              <Ionicons name="grid" size={18} color="#10b981" />
              <Text style={styles.featureText}>
                {language === 'it' ? '30+ Formazioni con varianti' : '30+ Formations with variants'}
              </Text>
            </View>
            <View style={styles.featureItem}>
              <Ionicons name="shield" size={18} color="#ef4444" />
              <Text style={styles.featureText}>
                {language === 'it' ? 'Counter Engine v6 completo' : 'Complete Counter Engine v6'}
              </Text>
            </View>
            <View style={styles.featureItem}>
              <Ionicons name="search" size={18} color="#f59e0b" />
              <Text style={styles.featureText}>
                {language === 'it' ? 'Consigli Scout dettagliati' : 'Detailed Scout tips'}
              </Text>
            </View>
            <View style={styles.featureItem}>
              <Ionicons name="sparkles" size={18} color="#8b5cf6" />
              <Text style={styles.featureText}>
                {language === 'it' ? 'AI Tattico (GPT-4)' : 'Tactical AI (GPT-4)'}
              </Text>
            </View>
            <View style={styles.featureItem}>
              <Ionicons name="trending-up" size={18} color="#3b82f6" />
              <Text style={styles.featureText}>
                {language === 'it' ? 'Tattiche META 2025/2026' : 'META 2025/2026 Tactics'}
              </Text>
            </View>
          </View>
        </View>

        {/* Credits */}
        <View style={styles.creditsSection}>
          <Text style={styles.creditsTitle}>
            {language === 'it' ? 'Crediti' : 'Credits'}
          </Text>
          <Text style={styles.creditsText}>
            {language === 'it' 
              ? 'Dati tattici raccolti da YouTube, Forum ufficiali e community Top Eleven'
              : 'Tactical data collected from YouTube, Official forums and Top Eleven community'}
          </Text>
          <Text style={styles.creditsText}>
            © 2026 Top Eleven Tactics Wiki
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0f1a',
  },
  header: {
    padding: 20,
    paddingBottom: 16,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingTop: 0,
    paddingBottom: 100,
  },
  appInfoCard: {
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderRadius: 20,
    padding: 24,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.2)',
    marginBottom: 24,
  },
  appIcon: {
    width: 80,
    height: 80,
    borderRadius: 20,
    backgroundColor: 'rgba(16,185,129,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  appName: {
    color: '#fff',
    fontSize: 22,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  appVersion: {
    color: '#10b981',
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 12,
  },
  appDescription: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 14,
    textAlign: 'center',
  },
  section: {
    marginBottom: 24,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
  languageOptions: {
    gap: 12,
  },
  languageButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    gap: 12,
  },
  languageButtonActive: {
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderColor: 'rgba(16,185,129,0.3)',
  },
  flagEmoji: {
    fontSize: 24,
  },
  languageText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 16,
    fontWeight: '500',
    flex: 1,
  },
  languageTextActive: {
    color: '#fff',
  },
  featuresList: {
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: 16,
    padding: 16,
    gap: 14,
  },
  featureItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  featureText: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 14,
  },
  creditsSection: {
    alignItems: 'center',
    paddingTop: 20,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  creditsTitle: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  creditsText: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: 12,
    textAlign: 'center',
    marginBottom: 4,
  },
});
