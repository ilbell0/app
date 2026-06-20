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
  TextInput,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { COUNTER_ENGINE, FORMATIONS } from '@/src/data';
import PitchDiagram from '@/src/components/PitchDiagram';

// mappa nome modulo -> posizioni, per disegnare il mini-campo del counter
const POSITIONS: Record<string, string[]> = {};
(FORMATIONS as any[]).forEach((f) => { POSITIONS[f.name] = f.positions; });

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
  alt_fr?: Record<string, string>;
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
  const [search, setSearch] = useState('');
  const [showAlt, setShowAlt] = useState(false);
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
  }, [fadeAnim, modalVisible]);

  const fetchData = async () => {
    setCounterEngine(COUNTER_ENGINE as CounterEngine[]);
    setLoading(false);
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

  // cerca per nome o per numero: "3-3-2-2" trova anche notazioni avanzate
  const qDigits = search.replace(/\D/g, '');
  const matchesSearch = (ce: CounterEngine) => {
    if (!search.trim()) return true;
    if (ce.av.toLowerCase().includes(search.toLowerCase().trim())) return true;
    return qDigits.length > 0 && ce.av.replace(/\D/g, '').includes(qDigits);
  };
  const filteredFormations = counterEngine.filter((ce) =>
    matchesSearch(ce) && (search.trim() ? true : searchCategory === 'all' || ce.cat === searchCategory)
  );

  const openModal = (formation: CounterEngine) => {
    setSelectedFormation(formation);
    setSelectedLevel('pari');
    setShowAlt(false);
    setModalVisible(true);
  };

  const currentScenario = selectedFormation?.[selectedLevel];
  // modulo/frecce attivi: principale o alternativa, in base alla selezione
  const hasAlt = !!currentScenario && !!currentScenario.alt && currentScenario.alt !== currentScenario.mod;
  const activeMod = currentScenario ? (showAlt && hasAlt ? currentScenario.alt : currentScenario.mod) : '';
  const activeFr = currentScenario
    ? (showAlt && hasAlt ? (currentScenario.alt_fr || currentScenario.fr) : currentScenario.fr)
    : {};

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

      {/* Search */}
      <View style={styles.searchRow}>
        <Ionicons name="search" size={16} color={NothingTheme.colors.textTertiary} />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder={language === 'it' ? 'Cerca avversario (es. 3-3-2-2)' : 'Search opponent (e.g. 3-3-2-2)'}
          placeholderTextColor={NothingTheme.colors.textTertiary}
          autoCapitalize="none"
          autoCorrect={false}
        />
        {search.length > 0 && (
          <TouchableOpacity onPress={() => setSearch('')}>
            <Ionicons name="close-circle" size={16} color={NothingTheme.colors.textTertiary} />
          </TouchableOpacity>
        )}
      </View>

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
                  onPress={() => { setSelectedLevel(level); setShowAlt(false); }}
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
                  {/* Recommended Formation + alternativa selezionabile */}
                  <View style={styles.recommendedSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'FORMAZIONE' : 'FORMATION'}
                    </Text>
                    {hasAlt ? (
                      <View style={styles.modSwitch}>
                        <TouchableOpacity
                          style={[styles.modSwitchBtn, !showAlt && styles.modSwitchBtnActive]}
                          onPress={() => setShowAlt(false)}
                          activeOpacity={0.7}
                        >
                          <Text style={[styles.modSwitchLabel, !showAlt && styles.modSwitchLabelActive]}>
                            {language === 'it' ? 'PRINCIPALE' : 'MAIN'}
                          </Text>
                          <Text style={[styles.modSwitchName, !showAlt && styles.modSwitchNameActive]}>
                            {currentScenario.mod}
                          </Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          style={[styles.modSwitchBtn, showAlt && styles.modSwitchBtnActive]}
                          onPress={() => setShowAlt(true)}
                          activeOpacity={0.7}
                        >
                          <Text style={[styles.modSwitchLabel, showAlt && styles.modSwitchLabelActive]}>
                            {language === 'it' ? 'ALTERNATIVA' : 'ALTERNATIVE'}
                          </Text>
                          <Text style={[styles.modSwitchName, showAlt && styles.modSwitchNameActive]}>
                            {currentScenario.alt}
                          </Text>
                        </TouchableOpacity>
                      </View>
                    ) : (
                      <View style={styles.formationBox}>
                        <Text style={styles.recommendedFormation}>{currentScenario.mod}</Text>
                      </View>
                    )}
                  </View>

                  {/* Mini-campo del modulo attivo (principale o alternativa) */}
                  {POSITIONS[activeMod] && (
                    <View style={styles.pitchSection}>
                      <PitchDiagram positions={POSITIONS[activeMod]} arrows={activeFr} />
                    </View>
                  )}

                  {/* Tactical Settings Grid */}
                  <View style={styles.tacticsSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? 'IMPOSTAZIONI' : 'SETTINGS'}
                    </Text>
                    {hasAlt && (
                      <Text style={styles.sharedNote}>
                        {language === 'it'
                          ? 'Valide per entrambi i moduli · cambiano solo le frecce'
                          : 'Same for both formations · only arrows differ'}
                      </Text>
                    )}
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

                  {/* Position Arrows (del modulo attivo) */}
                  <View style={styles.arrowsSection}>
                    <Text style={styles.sectionLabel}>
                      {language === 'it' ? `FRECCE · ${activeMod}` : `ARROWS · ${activeMod}`}
                    </Text>
                    <View style={styles.arrowsGrid}>
                      {Object.entries(activeFr).map(([position, arrow]) => (
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
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 24,
    marginTop: 14,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  searchInput: {
    flex: 1,
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    padding: 0,
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
  modSwitch: {
    flexDirection: 'row',
    gap: 8,
  },
  modSwitchBtn: {
    flex: 1,
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 10,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  modSwitchBtnActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  modSwitchLabel: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
    marginBottom: 6,
  },
  modSwitchLabelActive: {
    color: NothingTheme.colors.accent,
  },
  modSwitchName: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: 0.5,
    textAlign: 'center',
  },
  modSwitchNameActive: {
    color: NothingTheme.colors.textPrimary,
  },
  pitchSection: {
    marginBottom: 24,
  },
  sharedNote: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 11,
    fontStyle: 'italic',
    marginTop: -6,
    marginBottom: 12,
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
