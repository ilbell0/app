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
import { NothingTheme } from '@/src/theme/NothingTheme';
import { APP_META } from '@/src/data';

export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const { language, setLanguage } = useLanguage();

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <ScrollView 
        style={styles.scrollView} 
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>SETTINGS</Text>
        </View>

        <View style={styles.divider} />

        {/* App Info */}
        <View style={styles.appInfoCard}>
          <View style={styles.dotGrid}>
            {[...Array(9)].map((_, i) => (
              <View 
                key={i} 
                style={[
                  styles.dot,
                  (i === 4 || i === 0 || i === 8) && styles.dotActive
                ]} 
              />
            ))}
          </View>
          <Text style={styles.appName}>TOP ELEVEN</Text>
          <Text style={styles.appSubname}>TACTICS</Text>
          <View style={styles.versionBadge}>
            <Text style={styles.versionText}>{APP_META.settingsBadge}</Text>
          </View>
        </View>

        <View style={styles.divider} />

        {/* Language Section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            {language === 'it' ? 'LINGUA' : 'LANGUAGE'}
          </Text>
          
          <TouchableOpacity
            style={[
              styles.languageOption,
              language === 'it' && styles.languageOptionActive,
            ]}
            onPress={() => setLanguage('it')}
          >
            <View style={styles.languageInfo}>
              <Text style={styles.flagText}>IT</Text>
              <Text style={[
                styles.languageText,
                language === 'it' && styles.languageTextActive,
              ]}>
                Italiano
              </Text>
            </View>
            {language === 'it' && (
              <View style={styles.checkIcon}>
                <Ionicons name="checkmark" size={16} color={NothingTheme.colors.accent} />
              </View>
            )}
          </TouchableOpacity>
          
          <TouchableOpacity
            style={[
              styles.languageOption,
              language === 'en' && styles.languageOptionActive,
            ]}
            onPress={() => setLanguage('en')}
          >
            <View style={styles.languageInfo}>
              <Text style={styles.flagText}>EN</Text>
              <Text style={[
                styles.languageText,
                language === 'en' && styles.languageTextActive,
              ]}>
                English
              </Text>
            </View>
            {language === 'en' && (
              <View style={styles.checkIcon}>
                <Ionicons name="checkmark" size={16} color={NothingTheme.colors.accent} />
              </View>
            )}
          </TouchableOpacity>
        </View>

        <View style={styles.divider} />

        {/* Content Stats */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            {language === 'it' ? 'CONTENUTI' : 'CONTENTS'}
          </Text>
          
          <View style={styles.statsList}>
            <View style={styles.statItem}>
              <Text style={styles.statValue}>{APP_META.formations}</Text>
              <Text style={styles.statLabel}>
                {language === 'it' ? 'Formazioni' : 'Formations'}
              </Text>
            </View>
            <View style={styles.statDivider} />
            <View style={styles.statItem}>
              <Text style={styles.statValue}>{APP_META.counters}</Text>
              <Text style={styles.statLabel}>
                {language === 'it' ? 'Counter' : 'Counters'}
              </Text>
            </View>
            <View style={styles.statDivider} />
            <View style={styles.statItem}>
              <Text style={styles.statValue}>{APP_META.academySections}</Text>
              <Text style={styles.statLabel}>ACADEMY</Text>
            </View>
          </View>
        </View>

        <View style={styles.divider} />

        {/* Credits */}
        <View style={styles.credits}>
          <Text style={styles.creditsText}>
            {language === 'it' 
              ? `Dati da YouTube, forum e community - ${APP_META.datasets} dataset offline`
              : `Data from YouTube, forums and community - ${APP_META.datasets} offline datasets`}
          </Text>
          <Text style={styles.copyright}>
            (C) 2026 TOP ELEVEN TACTICS WIKI
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 100,
  },
  header: {
    padding: 24,
    paddingBottom: 16,
  },
  headerTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
  },
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
    marginHorizontal: 24,
  },
  appInfoCard: {
    alignItems: 'center',
    paddingVertical: 40,
    paddingHorizontal: 24,
  },
  dotGrid: {
    width: 56,
    height: 56,
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 6,
    marginBottom: 24,
  },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: NothingTheme.colors.dotInactive,
  },
  dotActive: {
    backgroundColor: NothingTheme.colors.dotActive,
  },
  appName: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
  },
  appSubname: {
    color: NothingTheme.colors.accent,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
    marginTop: -4,
  },
  versionBadge: {
    marginTop: 16,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 4,
  },
  versionText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
  },
  section: {
    padding: 24,
  },
  sectionTitle: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 2,
    marginBottom: 16,
  },
  languageOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  languageOptionActive: {
    borderColor: NothingTheme.colors.accent,
    backgroundColor: NothingTheme.colors.accentMuted,
  },
  languageInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  flagText: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    fontWeight: '700',
    width: 24,
  },
  languageText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 14,
    fontWeight: '500',
  },
  languageTextActive: {
    color: NothingTheme.colors.textPrimary,
  },
  checkIcon: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: NothingTheme.colors.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  statsList: {
    flexDirection: 'row',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    overflow: 'hidden',
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 20,
  },
  statValue: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 28,
    fontWeight: '700',
  },
  statLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1,
    marginTop: 4,
    textTransform: 'uppercase',
  },
  statDivider: {
    width: 1,
    backgroundColor: NothingTheme.colors.border,
  },
  credits: {
    alignItems: 'center',
    paddingVertical: 40,
    paddingHorizontal: 24,
  },
  creditsText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 11,
    textAlign: 'center',
    marginBottom: 8,
  },
  copyright: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1,
  },
});
