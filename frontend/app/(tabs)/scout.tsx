import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Animated,
} from 'react-native';
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

// Macro-gruppi: ogni categoria fine dei dati confluisce in una delle 3 aree,
// così tutti gli 82 consigli sono raggiungibili (prima il filtro ne copriva ~5).
const CATEGORIES = [
  { id: 'all', icon: 'apps-outline', label_en: 'All', label_it: 'Tutti' },
  { id: 'tactics', icon: 'git-compare-outline', label_en: 'Tactics', label_it: 'Tattica' },
  { id: 'squad', icon: 'people-outline', label_en: 'Squad', label_it: 'Reparti' },
  { id: 'club', icon: 'briefcase-outline', label_en: 'Club', label_it: 'Gestione' },
];

const MACRO_OF: Record<string, string> = {
  tactics: 'tactics', counter: 'tactics', scenario: 'tactics', arrows: 'tactics', meta: 'tactics',
  defense: 'squad', midfield: 'squad', attack: 'squad', skills: 'squad', training: 'squad',
  economy: 'club', market: 'club', budget: 'club', morale: 'club', general: 'club',
};

const MACRO_ICON: Record<string, string> = {
  tactics: 'git-compare-outline', squad: 'people-outline', club: 'briefcase-outline',
};

export default function ScoutScreen() {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const [tips, setTips] = useState<ScoutTip[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [selectedTip, setSelectedTip] = useState<ScoutTip | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [fadeAnim] = useState(new Animated.Value(0));

  useEffect(() => {
    fetchTips();
  }, []);

  useEffect(() => {
    if (modalVisible) {
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }).start();
    } else {
      fadeAnim.setValue(0);
    }
  }, [fadeAnim, modalVisible]);

  const fetchTips = async () => {
    setTips(SCOUT_TIPS as ScoutTip[]);
    setLoading(false);
  };

  const filteredTips = selectedCategory === 'all'
    ? tips
    : tips.filter((tip) => MACRO_OF[tip.category] === selectedCategory);

  const openTip = (tip: ScoutTip) => {
    setSelectedTip(tip);
    setModalVisible(true);
  };

  const getCategoryIcon = (category: string) => {
    return MACRO_ICON[MACRO_OF[category]] || 'document-outline';
  };

  if (loading) {
    return (
      <View style={[styles.container, styles.centered]}>
        <ActivityIndicator size="large" color={NothingTheme.colors.accent} />
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>SCOUT</Text>
        <Text style={styles.headerSubtitle}>TIPS</Text>
      </View>

      <View style={styles.divider} />

      {/* Category Filter */}
      <ScrollView 
        horizontal 
        showsHorizontalScrollIndicator={false}
        style={styles.filterScroll}
        contentContainerStyle={styles.filterContainer}
      >
        {CATEGORIES.map((cat) => (
          <TouchableOpacity
            key={cat.id}
            style={[
              styles.filterButton,
              selectedCategory === cat.id && styles.filterButtonActive,
            ]}
            onPress={() => setSelectedCategory(cat.id)}
          >
            <Ionicons
              name={cat.icon as any}
              size={14}
              color={selectedCategory === cat.id ? NothingTheme.colors.accent : NothingTheme.colors.textSecondary}
              style={{ marginRight: 6 }}
            />
            <Text style={[
              styles.filterButtonText,
              selectedCategory === cat.id && styles.filterButtonTextActive,
            ]}>
              {language === 'it' ? cat.label_it : cat.label_en}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <View style={styles.divider} />

      {/* Tips Count */}
      <View style={styles.countRow}>
        <Text style={styles.countText}>
          {filteredTips.length} {language === 'it' ? 'CONSIGLI' : 'TIPS'}
        </Text>
      </View>

      {/* Tips List */}
      <ScrollView 
        style={styles.scrollView} 
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {filteredTips.map((tip, index) => (
          <TouchableOpacity
            key={tip.id || index}
            style={styles.tipCard}
            onPress={() => openTip(tip)}
            activeOpacity={0.7}
          >
            <View style={styles.tipIconContainer}>
              <Ionicons 
                name={getCategoryIcon(tip.category) as any} 
                size={20} 
                color={NothingTheme.colors.textPrimary} 
              />
            </View>
            <View style={styles.tipContent}>
              <Text style={styles.tipTitle}>
                {language === 'it' ? tip.title_it : tip.title_en}
              </Text>
              <Text style={styles.tipPreview} numberOfLines={1}>
                {language === 'it' ? tip.content_it : tip.content_en}
              </Text>
            </View>
            <Ionicons 
              name="chevron-forward" 
              size={18} 
              color={NothingTheme.colors.textTertiary} 
            />
          </TouchableOpacity>
        ))}

        {filteredTips.length === 0 && (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>
              {language === 'it' ? 'Nessun consiglio trovato' : 'No tips found'}
            </Text>
          </View>
        )}
      </ScrollView>

      {/* Detail Modal */}
      <Modal
        animationType="slide"
        transparent={true}
        visible={modalVisible}
        onRequestClose={() => setModalVisible(false)}
      >
        <Animated.View style={[styles.modalOverlay, { opacity: fadeAnim }]}>
          <View style={[styles.modalContent, { paddingTop: insets.top + 10 }]}>
            {/* Modal Header */}
            <View style={styles.modalHeader}>
              <TouchableOpacity
                style={styles.closeButton}
                onPress={() => setModalVisible(false)}
              >
                <Ionicons name="close" size={24} color={NothingTheme.colors.textPrimary} />
              </TouchableOpacity>
              <View style={styles.modalIconContainer}>
                <Ionicons 
                  name={getCategoryIcon(selectedTip?.category || '') as any} 
                  size={32} 
                  color={NothingTheme.colors.accent} 
                />
              </View>
              <Text style={styles.modalTitle}>
                {language === 'it' ? selectedTip?.title_it : selectedTip?.title_en}
              </Text>
              <View style={styles.categoryBadge}>
                <Text style={styles.categoryBadgeText}>
                  {selectedTip?.category.toUpperCase()}
                </Text>
              </View>
            </View>

            <View style={styles.dividerModal} />

            {/* Content */}
            <ScrollView 
              style={styles.modalScroll}
              showsVerticalScrollIndicator={false}
            >
              <Text style={styles.modalContentText}>
                {language === 'it' ? selectedTip?.content_it : selectedTip?.content_en}
              </Text>
            </ScrollView>
          </View>
        </Animated.View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  centered: {
    justifyContent: 'center',
    alignItems: 'center',
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
  headerSubtitle: {
    color: NothingTheme.colors.accent,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
    marginTop: -4,
  },
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
    marginHorizontal: 24,
  },
  dividerModal: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
  },
  filterScroll: {
    flexGrow: 0,
  },
  filterContainer: {
    paddingHorizontal: 24,
    paddingVertical: 16,
    gap: 8,
  },
  filterButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    marginRight: 8,
  },
  filterButtonActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  filterButtonText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
  },
  filterButtonTextActive: {
    color: NothingTheme.colors.accent,
  },
  countRow: {
    paddingHorizontal: 24,
    paddingVertical: 12,
  },
  countText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 2,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 24,
    paddingTop: 0,
    paddingBottom: 100,
  },
  tipCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  tipIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: NothingTheme.colors.background,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
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
  tipPreview: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 14,
  },
  // Modal Styles
  modalOverlay: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  modalContent: {
    flex: 1,
  },
  modalHeader: {
    padding: 24,
    alignItems: 'center',
  },
  closeButton: {
    position: 'absolute',
    right: 24,
    top: 24,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modalIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: NothingTheme.colors.accentMuted,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  modalTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 20,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 12,
    paddingHorizontal: 48,
  },
  categoryBadge: {
    backgroundColor: NothingTheme.colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  categoryBadgeText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 2,
  },
  modalScroll: {
    flex: 1,
    padding: 24,
  },
  modalContentText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 15,
    lineHeight: 24,
  },
});
