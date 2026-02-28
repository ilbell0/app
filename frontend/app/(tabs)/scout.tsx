import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
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

const CATEGORIES = [
  { id: 'all', icon: 'apps', color: '#10b981' },
  { id: 'defense', icon: 'shield', color: '#3b82f6' },
  { id: 'midfield', icon: 'swap-horizontal', color: '#8b5cf6' },
  { id: 'attack', icon: 'flash', color: '#ef4444' },
  { id: 'training', icon: 'fitness', color: '#f59e0b' },
  { id: 'budget', icon: 'cash', color: '#10b981' },
  { id: 'tactics', icon: 'settings', color: '#6366f1' },
];

export default function ScoutScreen() {
  const insets = useSafeAreaInsets();
  const { t, language } = useLanguage();
  const [tips, setTips] = useState<ScoutTip[]>([]);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [loading, setLoading] = useState(true);
  const [expandedTip, setExpandedTip] = useState<string | null>(null);

  useEffect(() => {
    fetchTips();
  }, []);

  const fetchTips = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/scout-tips`);
      setTips(response.data);
    } catch (error) {
      console.error('Error fetching tips:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredTips = selectedCategory === 'all'
    ? tips
    : tips.filter((tip) => tip.category === selectedCategory);

  const getCategoryLabel = (category: string) => {
    const labels: { [key: string]: { en: string; it: string } } = {
      all: { en: 'All', it: 'Tutti' },
      defense: { en: 'Defense', it: 'Difesa' },
      midfield: { en: 'Midfield', it: 'Centrocampo' },
      attack: { en: 'Attack', it: 'Attacco' },
      training: { en: 'Training', it: 'Allenamento' },
      budget: { en: 'Budget', it: 'Budget' },
      tactics: { en: 'Tactics', it: 'Tattiche' },
    };
    return labels[category]?.[language] || category;
  };

  const getCategoryColor = (category: string) => {
    return CATEGORIES.find((c) => c.id === category)?.color || '#10b981';
  };

  const getCategoryIcon = (category: string) => {
    return CATEGORIES.find((c) => c.id === category)?.icon || 'help';
  };

  if (loading) {
    return (
      <View style={[styles.container, styles.centered]}>
        <ActivityIndicator size="large" color="#10b981" />
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{t('scoutTips')}</Text>
      </View>

      {/* Category Tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.categoryScroll}
        contentContainerStyle={styles.categoryContent}
      >
        {CATEGORIES.map((category) => (
          <TouchableOpacity
            key={category.id}
            style={[
              styles.categoryButton,
              selectedCategory === category.id && {
                backgroundColor: `${category.color}20`,
                borderColor: category.color,
              },
            ]}
            onPress={() => setSelectedCategory(category.id)}
          >
            <Ionicons
              name={category.icon as any}
              size={18}
              color={selectedCategory === category.id ? category.color : 'rgba(255,255,255,0.5)'}
            />
            <Text
              style={[
                styles.categoryText,
                selectedCategory === category.id && { color: category.color },
              ]}
            >
              {getCategoryLabel(category.id)}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Tips List */}
      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {filteredTips.map((tip) => (
          <TouchableOpacity
            key={tip.id}
            style={styles.tipCard}
            onPress={() => setExpandedTip(expandedTip === tip.id ? null : tip.id)}
            activeOpacity={0.8}
          >
            <View style={styles.tipHeader}>
              <View
                style={[
                  styles.tipIcon,
                  { backgroundColor: `${getCategoryColor(tip.category)}20` },
                ]}
              >
                <Ionicons
                  name={getCategoryIcon(tip.category) as any}
                  size={24}
                  color={getCategoryColor(tip.category)}
                />
              </View>
              <View style={styles.tipTitleContainer}>
                <Text style={styles.tipCategory}>
                  {getCategoryLabel(tip.category)}
                </Text>
                <Text style={styles.tipTitle}>
                  {language === 'it' ? tip.title_it : tip.title_en}
                </Text>
              </View>
              <Ionicons
                name={expandedTip === tip.id ? 'chevron-up' : 'chevron-down'}
                size={24}
                color="rgba(255,255,255,0.5)"
              />
            </View>

            {expandedTip === tip.id && (
              <View style={styles.tipContent}>
                <Text style={styles.tipText}>
                  {language === 'it' ? tip.content_it : tip.content_en}
                </Text>
              </View>
            )}
          </TouchableOpacity>
        ))}

        {filteredTips.length === 0 && (
          <View style={styles.emptyState}>
            <Ionicons name="search" size={48} color="rgba(255,255,255,0.2)" />
            <Text style={styles.emptyText}>{t('noData')}</Text>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0f1a',
  },
  centered: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    padding: 20,
    paddingBottom: 12,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  categoryScroll: {
    maxHeight: 50,
  },
  categoryContent: {
    paddingHorizontal: 20,
    gap: 10,
  },
  categoryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  categoryText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 13,
    fontWeight: '600',
  },
  scrollView: {
    flex: 1,
    marginTop: 16,
  },
  scrollContent: {
    padding: 20,
    paddingTop: 4,
    paddingBottom: 100,
  },
  tipCard: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  tipHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tipIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  tipTitleContainer: {
    flex: 1,
  },
  tipCategory: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  tipTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  tipContent: {
    marginTop: 16,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  tipText: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 14,
    lineHeight: 22,
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  emptyText: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 15,
    marginTop: 12,
  },
});
