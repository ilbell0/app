import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { APP_META, SCOUT_TIPS } from '@/src/data';
import CounterWizard from '@/src/components/CounterWizard';
import CompareModal from '@/src/components/CompareModal';

interface ScoutTip {
  id: string;
  category: string;
  title_en: string;
  title_it: string;
  content_en: string;
  content_it: string;
}

export default function HomeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const [tips, setTips] = useState<ScoutTip[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [wizardVisible, setWizardVisible] = useState(false);
  const [compareVisible, setCompareVisible] = useState(false);

  useEffect(() => {
    fetchTips();
  }, []);

  const fetchTips = async () => {
    // 3 consigli casuali, così il pull-to-refresh mostra contenuti diversi
    const all = [...(SCOUT_TIPS as ScoutTip[])];
    for (let i = all.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [all[i], all[j]] = [all[j], all[i]];
    }
    setTips(all.slice(0, 3));
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchTips();
    setRefreshing(false);
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={NothingTheme.colors.accent}
          />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerTop}>
            <View>
              <Text style={styles.welcomeText}>
                {language === 'it' ? 'Benvenuto' : 'Welcome'}
              </Text>
              <Text style={styles.headerTitle}>TOP ELEVEN</Text>
              <Text style={styles.headerSubtitle}>TACTICS</Text>
            </View>
            <View style={styles.logoContainer}>
              <View style={styles.dotGrid}>
                {[...Array(9)].map((_, i) => (
                  <View 
                    key={i} 
                    style={[
                      styles.dot,
                      (i === 4 || i === 1 || i === 7) && styles.dotActive
                    ]} 
                  />
                ))}
              </View>
            </View>
          </View>
          
          {/* Version Badge */}
          <View style={styles.versionBadge}>
            <Text style={styles.versionText}>{APP_META.settingsBadge}</Text>
          </View>
        </View>

        {/* Divider */}
        <View style={styles.divider} />

        {/* Trova counter — azione principale */}
        <View style={styles.section}>
          <TouchableOpacity style={styles.wizardCard} onPress={() => setWizardVisible(true)} activeOpacity={0.85}>
            <View style={styles.wizardIcon}>
              <Ionicons name="navigate" size={24} color={NothingTheme.colors.accent} />
            </View>
            <View style={styles.wizardContent}>
              <Text style={styles.wizardTitle}>{language === 'it' ? 'TROVA IL MIO COUNTER' : 'FIND MY COUNTER'}</Text>
              <Text style={styles.wizardSub}>
                {language === 'it' ? 'Modulo avversario → setup pronto' : 'Opponent formation → ready setup'}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={NothingTheme.colors.textTertiary} />
          </TouchableOpacity>

          <TouchableOpacity style={styles.compareCard} onPress={() => setCompareVisible(true)} activeOpacity={0.85}>
            <View style={styles.compareIcon}>
              <Ionicons name="git-compare" size={22} color={NothingTheme.colors.textPrimary} />
            </View>
            <View style={styles.wizardContent}>
              <Text style={styles.compareTitle}>{language === 'it' ? 'CONFRONTA MODULI' : 'COMPARE FORMATIONS'}</Text>
              <Text style={styles.wizardSub}>
                {language === 'it' ? 'Due moduli a confronto → chi vince' : 'Two formations head-to-head'}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={20} color={NothingTheme.colors.textTertiary} />
          </TouchableOpacity>
        </View>

        {/* Divider */}
        <View style={styles.divider} />

        {/* Stats Row */}
        <View style={styles.statsRow}>
          <View style={styles.statItem}>
            <Text style={styles.statNumber}>{APP_META.formations}</Text>
            <Text style={styles.statLabel}>
              {language === 'it' ? 'FORMAZIONI' : 'FORMATIONS'}
            </Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Text style={styles.statNumber}>{APP_META.academyItems}</Text>
            <Text style={styles.statLabel}>
              {language === 'it' ? 'SCHEDE ACADEMY' : 'ACADEMY CARDS'}
            </Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Text style={styles.statNumber}>{APP_META.counters}</Text>
            <Text style={styles.statLabel}>COUNTER</Text>
          </View>
        </View>

        {/* Divider */}
        <View style={styles.divider} />

        {/* Latest Tips */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>
              {language === 'it' ? 'CONSIGLI' : 'TIPS'}
            </Text>
            <TouchableOpacity onPress={() => router.push('/(tabs)/scout')}>
              <Text style={styles.seeAllText}>
                {language === 'it' ? 'VEDI TUTTI' : 'SEE ALL'}
              </Text>
            </TouchableOpacity>
          </View>
          
          {tips.map((tip, index) => (
            <TouchableOpacity
              key={tip.id || index}
              style={styles.tipCard}
              onPress={() => router.push('/(tabs)/scout')}
              activeOpacity={0.7}
            >
              <View style={styles.tipContent}>
                <Text style={styles.tipTitle}>
                  {language === 'it' ? tip.title_it : tip.title_en}
                </Text>
                <Text style={styles.tipDescription} numberOfLines={2}>
                  {language === 'it' ? tip.content_it : tip.content_en}
                </Text>
              </View>
              <Ionicons 
                name="chevron-forward" 
                size={20} 
                color={NothingTheme.colors.textTertiary} 
              />
            </TouchableOpacity>
          ))}
        </View>

        {/* Footer */}
        <View style={styles.footer}>
          <Text style={styles.footerText}>
            {APP_META.footerLabel}
          </Text>
          <Text style={styles.footerVersion}>{APP_META.datasets} DATASET</Text>
        </View>
      </ScrollView>

      <CounterWizard visible={wizardVisible} onClose={() => setWizardVisible(false)} />
      <CompareModal visible={compareVisible} onClose={() => setCompareVisible(false)} />
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
    paddingTop: 16,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  welcomeText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
    fontWeight: '500',
    letterSpacing: 2,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  headerTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 36,
    fontWeight: '700',
    letterSpacing: -1,
  },
  headerSubtitle: {
    color: NothingTheme.colors.accent,
    fontSize: 36,
    fontWeight: '700',
    letterSpacing: -1,
    marginTop: -8,
  },
  logoContainer: {
    width: 56,
    height: 56,
    borderRadius: 12,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotGrid: {
    width: 32,
    height: 32,
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.dotInactive,
  },
  dotActive: {
    backgroundColor: NothingTheme.colors.dotActive,
  },
  versionBadge: {
    alignSelf: 'flex-start',
    backgroundColor: NothingTheme.colors.accentMuted,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
    marginTop: 16,
  },
  versionText: {
    color: NothingTheme.colors.accent,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
  },
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
    marginHorizontal: 24,
  },
  section: {
    padding: 24,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  sectionTitle: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 2,
    marginBottom: 16,
  },
  seeAllText: {
    color: NothingTheme.colors.accent,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
  },
  quickActions: {
    flexDirection: 'row',
    gap: 12,
  },
  actionCard: {
    flex: 1,
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  actionIconContainer: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: NothingTheme.colors.background,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  actionLabel: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  statsRow: {
    flexDirection: 'row',
    paddingVertical: 24,
    paddingHorizontal: 24,
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
  },
  statNumber: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 32,
    fontWeight: '700',
    letterSpacing: -1,
  },
  statLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1,
    marginTop: 4,
  },
  statDivider: {
    width: 1,
    height: '100%',
    backgroundColor: NothingTheme.colors.divider,
  },
  tipCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 12,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  tipContent: {
    flex: 1,
    marginRight: 12,
  },
  tipTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 4,
  },
  tipDescription: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
    lineHeight: 18,
  },
  footer: {
    alignItems: 'center',
    paddingVertical: 32,
  },
  footerText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 2,
  },
  footerVersion: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    marginTop: 4,
  },
  academyWrap: {
    paddingHorizontal: 24,
    paddingBottom: 8,
  },
  academyCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: NothingTheme.colors.accent,
  },
  academyIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: NothingTheme.colors.accentMuted,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  academyContent: {
    flex: 1,
  },
  academyTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 15,
    fontWeight: '700',
    letterSpacing: 1,
  },
  academySub: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
    marginTop: 2,
  },
  wizardCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.accentMuted,
    borderRadius: 12,
    padding: 18,
    borderWidth: 1,
    borderColor: NothingTheme.colors.accent,
  },
  wizardIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: NothingTheme.colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  wizardContent: { flex: 1 },
  wizardTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 15,
    fontWeight: '700',
    letterSpacing: 1,
  },
  wizardSub: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 12,
    marginTop: 2,
  },
  compareCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 12,
    padding: 18,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    marginTop: 10,
  },
  compareIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: NothingTheme.colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  compareTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 15,
    fontWeight: '700',
    letterSpacing: 1,
  },
});
