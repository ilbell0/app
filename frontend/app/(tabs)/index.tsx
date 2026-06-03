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
import { SCOUT_TIPS } from '@/src/data';

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
  const { t, language } = useLanguage();
  const [tips, setTips] = useState<ScoutTip[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchTips();
  }, []);

  const fetchTips = async () => {
    setTips((SCOUT_TIPS as ScoutTip[]).slice(0, 3));
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchTips();
    setRefreshing(false);
  };

  const quickActions = [
    { icon: 'grid-outline', label: language === 'it' ? 'Formazioni' : 'Formations', route: '/(tabs)/formations' },
    { icon: 'shield-outline', label: language === 'it' ? 'Counter' : 'Counter', route: '/(tabs)/counters' },
    { icon: 'search-outline', label: 'Scout', route: '/(tabs)/scout' },
    { icon: 'school-outline', label: 'Academy', route: '/(tabs)/academy' },
  ];

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
            <Text style={styles.versionText}>META 2026</Text>
          </View>
        </View>

        {/* Divider */}
        <View style={styles.divider} />

        {/* Quick Access */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            {language === 'it' ? 'ACCESSO RAPIDO' : 'QUICK ACCESS'}
          </Text>
          <View style={styles.quickActions}>
            {quickActions.map((action, index) => (
              <TouchableOpacity
                key={index}
                style={styles.actionCard}
                onPress={() => router.push(action.route as any)}
                activeOpacity={0.7}
              >
                <View style={styles.actionIconContainer}>
                  <Ionicons 
                    name={action.icon as any} 
                    size={24} 
                    color={NothingTheme.colors.textPrimary} 
                  />
                </View>
                <Text style={styles.actionLabel}>{action.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* Academy Banner */}
        <View style={styles.academyWrap}>
          <TouchableOpacity
            style={styles.academyCard}
            onPress={() => router.push('/(tabs)/academy')}
            activeOpacity={0.8}
          >
            <View style={styles.academyIcon}>
              <Ionicons name="school" size={24} color={NothingTheme.colors.accent} />
            </View>
            <View style={styles.academyContent}>
              <Text style={styles.academyTitle}>ACADEMY 2026</Text>
              <Text style={styles.academySub}>
                {language === 'it' ? 'Ruoli · Meta · Abilità · Allenamento' : 'Roles · Meta · Skills · Training'}
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
            <Text style={styles.statNumber}>37</Text>
            <Text style={styles.statLabel}>
              {language === 'it' ? 'FORMAZIONI' : 'FORMATIONS'}
            </Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Text style={styles.statNumber}>19</Text>
            <Text style={styles.statLabel}>
              {language === 'it' ? 'RUOLI' : 'ROLES'}
            </Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Text style={styles.statNumber}>8</Text>
            <Text style={styles.statLabel}>META</Text>
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
            TOP ELEVEN TACTICS WIKI
          </Text>
          <Text style={styles.footerVersion}>v2.0</Text>
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
});
