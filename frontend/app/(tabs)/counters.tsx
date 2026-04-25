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
import axios from 'axios';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface CounterScenario {
  mod: string;
  alt: string;
  men: string;
  pass: string;
  stile: string;
  ctrl: string;
  press: string;
  cont: string;
  marc: string;
  fuo: string;
  fr: Record<string, string>;
  w: string;
}

interface CounterEngine {
  av: string;
  cat: string;
  meta?: boolean;
  forte: CounterScenario;
  pari: CounterScenario;
  debole: CounterScenario;
}

type ScenarioLevel = 'forte' | 'pari' | 'debole';

export default function CountersScreen() {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const [counterEngine, setCounterEngine] = useState<CounterEngine[]>([]);
  const [selectedFormation, setSelectedFormation] = useState<CounterEngine | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<ScenarioLevel>('pari');
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [searchCategory, setSearchCategory] = useState<string>('all');
  const [fadeAnim] = useState(new Animated.Value(0));

  useEffect(() => {
    fetchData();
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
  }, [modalVisible]);

  const fetchData = async () => {
    try {
      const res = await axios.get(`${API_URL}/api/counter-engine`);
      setCounterEngine(res.data);
    } catch (error) {
      console.error('Error fetching counter engine data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getCategoryLabel = (cat: string) => {
    const labels: Record<string, { en: string; it: string }> = {
      att: { en: 'ATT', it: 'ATT' },
      neu: { en: 'BAL', it: 'BIL' },
      dif: { en: 'DEF', it: 'DIF' },
    };
    return labels[cat]?.[language] || cat.toUpperCase();
  };

  const getLevelLabel = (level: ScenarioLevel) => {
    const labels: Record<ScenarioLevel, { en: string; it: string }> = {
      forte: { en: 'STRONGER', it: 'FORTE' },
      pari: { en: 'EQUAL', it: 'PARI' },
      debole: { en: 'WEAKER', it: 'DEBOLE' },
    };
    return labels[level][language];
  };

  const getArrowColor = (arrow: string) => {
    if (arrow === '↑') return '#FFFFFF';
    if (arrow === '↓') return NothingTheme.colors.accent;
    return NothingTheme.colors.textTertiary;
  };

  const filteredFormations = searchCategory === 'all'
    ? counterEngine
    : counterEngine.filter((ce) => ce.cat === searchCategory);

  const openModal = (formation: CounterEngine) => {
    setSelectedFormation(formation);
    setSelectedLevel('pari');
    setModalVisible(true);
  };

  const currentScenario = selectedFormation?.[selectedLevel];

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
        <Text style={styles.headerTitle}>COUNTER</Text>
        <Text style={styles.headerSubtitle}>ENGINE v6</Text>
      </View>

      <View style={styles.divider} />

      {/* Category Filter */}
      <View style={styles.filterContainer}>
        {['all', 'att', 'neu', 'dif'].map((cat) => (
          <TouchableOpacity
            key={cat}
            style={[
              styles.filterButton,
              searchCategory === cat && styles.filterButtonActive,
            ]}
            onPress={() => setSearchCategory(cat)}
          >
            <Text style={[
              styles.filterButtonText,
              searchCategory === cat && styles.filterButtonTextActive,
            ]}>
              {cat === 'all' ? 'ALL' : getCategoryLabel(cat)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.divider} />

      <ScrollView 
        style={styles.scrollView} 
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* Formation List */}
        {filteredFormations.map((ce, index) => (
          <TouchableOpacity
            key={index}
            style={styles.formationCard}
            onPress={() => openModal(ce)}
            activeOpacity={0.7}
          >
            <View style={styles.formationInfo}>
              <View style={styles.formationHeader}>
                <Text style={styles.formationName}>{ce.av}</Text>
                {ce.meta && (
                  <View style={styles.metaBadge}>
                    <Text style={styles.metaBadgeText}>META</Text>
                  </View>
                )}
              </View>
              <Text style={styles.counterPreview}>
                → {ce.pari.mod}
              </Text>
            </View>
            <View style={styles.categoryBadge}>
              <Text style={styles.categoryText}>{getCategoryLabel(ce.cat)}</Text>
            </View>
          </TouchableOpacity>
        ))}

        {filteredFormations.length === 0 && (
          <View style={styles.emptyState}>
            <Text style={styles.emptyText}>
              {language === 'it' ? 'Nessun risultato' : 'No results'}
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
              <View style={styles.modalTitleContainer}>
                <Text style={styles.modalLabel}>VS</Text>
                <Text style={styles.modalTitle}>{selectedFormation?.av}</Text>
                {selectedFormation?.meta && (
                  <View style={styles.metaBadgeLarge}>
                    <Text style={styles.metaBadgeText}>META 2026</Text>
                  </View>
                )}
              </View>
            </View>

            <View style={styles.dividerModal} />

            {/* Level Tabs */}
            <View style={styles.levelTabs}>
              {(['forte', 'pari', 'debole'] as ScenarioLevel[]).map((level) => (
                <TouchableOpacity
                  key={level}
                  style={[
                    styles.levelTab,
                    selectedLevel === level && styles.levelTabActive,
                  ]}
                  onPress={() => setSelectedLevel(level)}
                >
                  <Text style={[
                    styles.levelTabText,
                    selectedLevel === level && styles.levelTabTextActive,
                  ]}>
                    {getLevelLabel(level)}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <ScrollView style={styles.modalScroll} showsVerticalScrollIndicator={false}>
              {currentScenario && (
                <>
                  {/* Recommended Formation */}
                  <View style={styles.recommendedSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'FORMAZIONE' : 'FORMATION'}
                    </Text>
                    <View style={styles.formationBox}>
                      <Text style={styles.recommendedFormation}>{currentScenario.mod}</Text>
                      <Text style={styles.alternativeFormation}>
                        ALT: {currentScenario.alt}
                      </Text>
                    </View>
                  </View>

                  {/* Tactical Settings Grid */}
                  <View style={styles.tacticsSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'IMPOSTAZIONI' : 'SETTINGS'}
                    </Text>
                    <View style={styles.tacticsGrid}>
                      <View style={styles.tacticRow}>
                        <Text style={styles.tacticLabel}>
                          {language === 'it' ? 'Mentalità' : 'Mentality'}
                        </Text>
                        <Text style={styles.tacticValue}>{currentScenario.men}</Text>
                      </View>
                      <View style={styles.tacticRow}>
                        <Text style={styles.tacticLabel}>
                          {language === 'it' ? 'Passaggi' : 'Passing'}
                        </Text>
                        <Text style={styles.tacticValue}>{currentScenario.pass}</Text>
                      </View>
                      <View style={styles.tacticRow}>
                        <Text style={styles.tacticLabel}>
                          {language === 'it' ? 'Stile' : 'Style'}
                        </Text>
                        <Text style={styles.tacticValue}>{currentScenario.stile}</Text>
                      </View>
                      <View style={styles.tacticRow}>
                        <Text style={styles.tacticLabel}>Pressing</Text>
                        <Text style={styles.tacticValue}>{currentScenario.press}</Text>
                      </View>
                      <View style={styles.tacticRow}>
                        <Text style={styles.tacticLabel}>
                          {language === 'it' ? 'Marcatura' : 'Marking'}
                        </Text>
                        <Text style={styles.tacticValue}>{currentScenario.marc}</Text>
                      </View>
                      <View style={styles.tacticRow}>
                        <Text style={styles.tacticLabel}>
                          {language === 'it' ? 'Contrasti' : 'Tackling'}
                        </Text>
                        <Text style={styles.tacticValue}>{currentScenario.cont}</Text>
                      </View>
                    </View>
                  </View>

                  {/* Toggle Badges */}
                  <View style={styles.togglesSection}>
                    <View style={[
                      styles.toggleBadge,
                      currentScenario.ctrl === 'SI' && styles.toggleBadgeActive,
                    ]}>
                      <Text style={[
                        styles.toggleText,
                        currentScenario.ctrl === 'SI' && styles.toggleTextActive,
                      ]}>
                        {language === 'it' ? 'CONTROPIEDE' : 'COUNTER'}
                      </Text>
                      <Text style={[
                        styles.toggleValue,
                        currentScenario.ctrl === 'SI' && styles.toggleValueActive,
                      ]}>
                        {currentScenario.ctrl}
                      </Text>
                    </View>
                    <View style={[
                      styles.toggleBadge,
                      currentScenario.fuo === 'SI' && styles.toggleBadgeActive,
                    ]}>
                      <Text style={[
                        styles.toggleText,
                        currentScenario.fuo === 'SI' && styles.toggleTextActive,
                      ]}>
                        {language === 'it' ? 'FUORIGIOCO' : 'OFFSIDE'}
                      </Text>
                      <Text style={[
                        styles.toggleValue,
                        currentScenario.fuo === 'SI' && styles.toggleValueActive,
                      ]}>
                        {currentScenario.fuo}
                      </Text>
                    </View>
                  </View>

                  {/* Position Arrows */}
                  <View style={styles.arrowsSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'FRECCE' : 'ARROWS'}
                    </Text>
                    <View style={styles.arrowsGrid}>
                      {Object.entries(currentScenario.fr).map(([position, arrow]) => (
                        <View key={position} style={styles.arrowItem}>
                          <Text style={styles.positionLabel}>{position}</Text>
                          <Text style={[styles.arrowIcon, { color: getArrowColor(arrow) }]}>
                            {arrow}
                          </Text>
                        </View>
                      ))}
                    </View>
                  </View>

                  {/* Tactical Tip */}
                  <View style={styles.tipSection}>
                    <Text style={styles.sectionLabel}>TIP</Text>
                    <View style={styles.tipBox}>
                      <Text style={styles.tipText}>{currentScenario.w}</Text>
                    </View>
                  </View>
                </>
              )}
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
  filterContainer: {
    flexDirection: 'row',
    padding: 24,
    gap: 8,
  },
  filterButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
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
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 24,
    paddingTop: 0,
    paddingBottom: 100,
  },
  formationCard: {
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
  formationInfo: {
    flex: 1,
  },
  formationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  formationName: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 16,
    fontWeight: '600',
  },
  metaBadge: {
    backgroundColor: NothingTheme.colors.accentMuted,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 2,
  },
  metaBadgeLarge: {
    backgroundColor: NothingTheme.colors.accentMuted,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
    marginTop: 8,
  },
  metaBadgeText: {
    color: NothingTheme.colors.accent,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  counterPreview: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
  },
  categoryBadge: {
    backgroundColor: NothingTheme.colors.background,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  categoryText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1,
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
  modalTitleContainer: {
    alignItems: 'center',
  },
  modalLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 2,
    marginBottom: 4,
  },
  modalTitle: {
    color: NothingTheme.colors.accent,
    fontSize: 32,
    fontWeight: '700',
    letterSpacing: 1,
  },
  levelTabs: {
    flexDirection: 'row',
    padding: 24,
    gap: 8,
  },
  levelTab: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
  },
  levelTabActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  levelTabText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
  },
  levelTabTextActive: {
    color: NothingTheme.colors.accent,
  },
  modalScroll: {
    flex: 1,
    paddingHorizontal: 24,
  },
  sectionLabel: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 2,
    marginBottom: 12,
  },
  recommendedSection: {
    marginBottom: 24,
  },
  formationBox: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 20,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  recommendedFormation: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 1,
    marginBottom: 4,
  },
  alternativeFormation: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
    letterSpacing: 1,
  },
  tacticsSection: {
    marginBottom: 24,
  },
  tacticsGrid: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    overflow: 'hidden',
  },
  tacticRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 14,
    borderBottomWidth: 1,
    borderBottomColor: NothingTheme.colors.border,
  },
  tacticLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
  },
  tacticValue: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 12,
    fontWeight: '600',
  },
  togglesSection: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 24,
  },
  toggleBadge: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  toggleBadgeActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  toggleText: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  toggleTextActive: {
    color: NothingTheme.colors.textPrimary,
  },
  toggleValue: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 12,
    fontWeight: '700',
  },
  toggleValueActive: {
    color: NothingTheme.colors.accent,
  },
  arrowsSection: {
    marginBottom: 24,
  },
  arrowsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  arrowItem: {
    alignItems: 'center',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 12,
    minWidth: 56,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  positionLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 10,
    fontWeight: '600',
    marginBottom: 4,
  },
  arrowIcon: {
    fontSize: 20,
    fontWeight: '700',
  },
  tipSection: {
    marginBottom: 40,
  },
  tipBox: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 16,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    borderLeftWidth: 3,
    borderLeftColor: NothingTheme.colors.accent,
  },
  tipText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
  },
});
