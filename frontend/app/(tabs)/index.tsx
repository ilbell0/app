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
import { useAuth } from '../../src/context/AuthContext';
import { useLanguage } from '../../src/context/LanguageContext';
import axios from 'axios';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

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
  const { user, isAuthenticated } = useAuth();
  const { t, language } = useLanguage();
  const [tips, setTips] = useState<ScoutTip[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchTips();
  }, []);

  const fetchTips = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/scout-tips`);
      setTips(response.data.slice(0, 3)); // Show only 3 tips
    } catch (error) {
      console.error('Error fetching tips:', error);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchTips();
    setRefreshing(false);
  };

  const quickActions = [
    { id: 'formations', icon: 'grid', label: t('viewFormations'), route: '/(tabs)/formations' },
    { id: 'counters', icon: 'shield', label: t('counterTactics'), route: '/(tabs)/counters' },
    { id: 'scout', icon: 'search', label: t('scoutTips'), route: '/(tabs)/scout' },
    { id: 'ai', icon: 'sparkles', label: t('askAI'), route: '/(tabs)/ai-chat' },
  ];

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#10b981" />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <View>
            <Text style={styles.welcomeText}>
              {t('welcomeBack')}, {isAuthenticated ? user?.name?.split(' ')[0] : t('guest')}
            </Text>
            <Text style={styles.headerTitle}>{t('appName')}</Text>
          </View>
          <View style={styles.logoContainer}>
            <Ionicons name="football" size={40} color="#10b981" />
          </View>
        </View>

        {/* Quick Access */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('quickAccess')}</Text>
          <View style={styles.quickActions}>
            {quickActions.map((action) => (
              <TouchableOpacity
                key={action.id}
                style={styles.quickActionButton}
                onPress={() => router.push(action.route as any)}
              >
                <View style={styles.quickActionIcon}>
                  <Ionicons name={action.icon as any} size={28} color="#10b981" />
                </View>
                <Text style={styles.quickActionLabel}>{action.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* Latest Tips */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('latestTips')}</Text>
          {tips.map((tip) => (
            <TouchableOpacity
              key={tip.id}
              style={styles.tipCard}
              onPress={() => router.push('/(tabs)/scout')}
            >
              <View style={styles.tipIcon}>
                <Ionicons
                  name={
                    tip.category === 'defense'
                      ? 'shield'
                      : tip.category === 'midfield'
                      ? 'swap-horizontal'
                      : tip.category === 'attack'
                      ? 'flash'
                      : tip.category === 'training'
                      ? 'fitness'
                      : tip.category === 'budget'
                      ? 'cash'
                      : 'settings'
                  }
                  size={24}
                  color="#10b981"
                />
              </View>
              <View style={styles.tipContent}>
                <Text style={styles.tipTitle}>
                  {language === 'it' ? tip.title_it : tip.title_en}
                </Text>
                <Text style={styles.tipDescription} numberOfLines={2}>
                  {language === 'it' ? tip.content_it : tip.content_en}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color="rgba(255,255,255,0.3)" />
            </TouchableOpacity>
          ))}
        </View>

        {/* AI Assistant Banner */}
        <TouchableOpacity
          style={styles.aiBanner}
          onPress={() => router.push('/(tabs)/ai-chat')}
        >
          <View style={styles.aiBannerContent}>
            <Ionicons name="sparkles" size={32} color="#10b981" />
            <View style={styles.aiBannerText}>
              <Text style={styles.aiBannerTitle}>{t('aiAssistant')}</Text>
              <Text style={styles.aiBannerDescription}>
                {language === 'it'
                  ? 'Chiedi all\'AI qualsiasi domanda tattica!'
                  : 'Ask AI any tactical question!'}
              </Text>
            </View>
          </View>
          <Ionicons name="arrow-forward" size={24} color="#10b981" />
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0f1a',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 20,
    paddingBottom: 100,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 32,
  },
  welcomeText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 14,
    marginBottom: 4,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  logoContainer: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: 'rgba(16,185,129,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: 'rgba(16,185,129,0.3)',
  },
  section: {
    marginBottom: 28,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '600',
    marginBottom: 16,
  },
  quickActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  quickActionButton: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  quickActionIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: 'rgba(16,185,129,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  quickActionLabel: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '500',
    textAlign: 'center',
  },
  tipCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  tipIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: 'rgba(16,185,129,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  tipContent: {
    flex: 1,
  },
  tipTitle: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
    marginBottom: 4,
  },
  tipDescription: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 13,
    lineHeight: 18,
  },
  aiBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(16,185,129,0.1)',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.3)',
  },
  aiBannerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  aiBannerText: {
    marginLeft: 16,
    flex: 1,
  },
  aiBannerTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 4,
  },
  aiBannerDescription: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 13,
  },
});
