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
import { FORMATIONS } from '@/src/data';

interface Variant {
  name_en: string;
  name_it: string;
  mentality: string;
  mentality_it: string;
  passing_focus: string;
  passing_focus_it: string;
  passing_style: string;
  passing_style_it: string;
  pressing: string;
  pressing_it: string;
  marking: string;
  marking_it: string;
  offside_trap: boolean;
  counter_attack: boolean;
  arrows: Record<string, string>;
  best_against: string[];
  tip_en: string;
  tip_it: string;
}

interface OpponentSettings {
  mentality: string;
  mentality_it: string;
  focus_passing: string;
  focus_passing_it: string;
  passing_style: string;
  passing_style_it: string;
  counter_attack: boolean;
  pressing: string;
  pressing_it: string;
  tackling: string;
  tackling_it: string;
  marking: string;
  marking_it: string;
  offside_trap: boolean;
  tip_en: string;
  tip_it: string;
  arrows?: Record<string, string>;
  variant?: string;
}

interface Formation {
  id: string;
  name: string;
  description_en: string;
  description_it: string;
  positions: string[];
  strengths_en: string[];
  strengths_it: string[];
  weaknesses_en: string[];
  weaknesses_it: string[];
  tactic_type_en?: string;
  tactic_type_it?: string;
  arrows?: string;
  defense_count?: number;
  effective_against?: string[];
  vulnerable_to?: string[];
  variants?: {
    A?: Variant;
    B?: Variant;
    C?: Variant;
  };
  opponent_settings?: {
    strong: OpponentSettings;
    equal: OpponentSettings;
    weak: OpponentSettings;
  };
}

export default function FormationsScreen() {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const [formations, setFormations] = useState<Formation[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedFormation, setSelectedFormation] = useState<Formation | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<'strong' | 'equal' | 'weak'>('equal');
  const [modalVisible, setModalVisible] = useState(false);
  const [fadeAnim] = useState(new Animated.Value(0));
  const [defenseFilter, setDefenseFilter] = useState<'all' | 3 | 4 | 5>('all');

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
    setFormations(FORMATIONS as Formation[]);
    setLoading(false);
  };

  const getLevelLabel = (level: string) => {
    const labels: Record<string, { en: string; it: string }> = {
      strong: { en: 'STRONGER', it: 'FORTE' },
      equal: { en: 'EQUAL', it: 'PARI' },
      weak: { en: 'WEAKER', it: 'DEBOLE' },
    };
    return labels[level]?.[language] || level;
  };

  const openModal = (formation: Formation) => {
    setSelectedFormation(formation);
    setSelectedLevel('equal');
    setModalVisible(true);
  };

  const currentSettings = selectedFormation?.opponent_settings?.[selectedLevel];

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
        <Text style={styles.headerTitle}>FORMA</Text>
        <Text style={styles.headerSubtitle}>TIONS</Text>
        <Text style={styles.headerCount}>{formations.filter(f => defenseFilter === 'all' || f.defense_count === defenseFilter).length}</Text>
      </View>

      <View style={styles.divider} />

      {/* Defense Filter */}
      <View style={styles.defFilter}>
        {([['all', language === 'it' ? 'TUTTE' : 'ALL'], [3, 'DIF 3'], [4, 'DIF 4'], [5, 'DIF 5']] as const).map(([val, lab]) => (
          <TouchableOpacity
            key={String(val)}
            style={[styles.defBtn, defenseFilter === val && styles.defBtnActive]}
            onPress={() => setDefenseFilter(val as any)}
          >
            <Text style={[styles.defBtnText, defenseFilter === val && styles.defBtnTextActive]}>{lab}</Text>
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
        {formations.filter(f => defenseFilter === 'all' || f.defense_count === defenseFilter).map((formation, index) => (
          <TouchableOpacity
            key={formation.id || index}
            style={styles.formationCard}
            onPress={() => openModal(formation)}
            activeOpacity={0.7}
          >
            <View style={styles.formationInfo}>
              <View style={styles.formationHeader}>
                <Text style={styles.formationName}>{formation.name}</Text>
                {formation.tactic_type_en?.includes('META') && (
                  <View style={styles.metaBadge}>
                    <Text style={styles.metaBadgeText}>META</Text>
                  </View>
                )}
              </View>
              <Text style={styles.formationPositions}>
                {formation.positions?.join(' · ')}
              </Text>
            </View>
            <Ionicons 
              name="chevron-forward" 
              size={18} 
              color={NothingTheme.colors.textTertiary} 
            />
          </TouchableOpacity>
        ))}
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
              <Text style={styles.modalTitle}>{selectedFormation?.name}</Text>
              {selectedFormation?.tactic_type_en && (
                <View style={styles.tacticTypeBadge}>
                  <Text style={styles.tacticTypeText}>
                    {language === 'it' 
                      ? selectedFormation.tactic_type_it 
                      : selectedFormation.tactic_type_en}
                  </Text>
                </View>
              )}
            </View>

            <View style={styles.dividerModal} />

            {/* Level Tabs */}
            <View style={styles.levelTabs}>
              {(['strong', 'equal', 'weak'] as const).map((level) => (
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
              {/* Description */}
              <View style={styles.descriptionSection}>
                <Text style={styles.sectionLabel}>
                  {language === 'it' ? 'DESCRIZIONE' : 'DESCRIPTION'}
                </Text>
                <Text style={styles.descriptionText}>
                  {language === 'it' 
                    ? selectedFormation?.description_it 
                    : selectedFormation?.description_en}
                </Text>
              </View>

              {/* Arrows Info */}
              {selectedFormation?.arrows && (
                <View style={styles.arrowsInfo}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'FRECCE' : 'ARROWS'}
                  </Text>
                  <View style={styles.arrowsBox}>
                    <Text style={styles.arrowsText}>{selectedFormation.arrows}</Text>
                  </View>
                </View>
              )}

              {/* Tactical Settings */}
              {currentSettings && (
                <View style={styles.tacticsSection}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'IMPOSTAZIONI' : 'SETTINGS'}
                  </Text>
                  <View style={styles.tacticsGrid}>
                    <View style={styles.tacticRow}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Mentalità' : 'Mentality'}
                      </Text>
                      <Text style={styles.tacticValue}>
                        {language === 'it' ? currentSettings.mentality_it : currentSettings.mentality}
                      </Text>
                    </View>
                    <View style={styles.tacticRow}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Passaggi' : 'Passing'}
                      </Text>
                      <Text style={styles.tacticValue}>
                        {language === 'it' ? currentSettings.focus_passing_it : currentSettings.focus_passing}
                      </Text>
                    </View>
                    <View style={styles.tacticRow}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Stile' : 'Style'}
                      </Text>
                      <Text style={styles.tacticValue}>
                        {language === 'it' ? currentSettings.passing_style_it : currentSettings.passing_style}
                      </Text>
                    </View>
                    <View style={styles.tacticRow}>
                      <Text style={styles.tacticLabel}>Pressing</Text>
                      <Text style={styles.tacticValue}>
                        {language === 'it' ? currentSettings.pressing_it : currentSettings.pressing}
                      </Text>
                    </View>
                    <View style={styles.tacticRow}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Marcatura' : 'Marking'}
                      </Text>
                      <Text style={styles.tacticValue}>
                        {language === 'it' ? currentSettings.marking_it : currentSettings.marking}
                      </Text>
                    </View>
                    <View style={styles.tacticRow}>
                      <Text style={styles.tacticLabel}>
                        {language === 'it' ? 'Contrasti' : 'Tackling'}
                      </Text>
                      <Text style={styles.tacticValue}>
                        {language === 'it' ? currentSettings.tackling_it : currentSettings.tackling}
                      </Text>
                    </View>
                  </View>
                </View>
              )}

              {/* Toggles */}
              {currentSettings && (
                <View style={styles.togglesSection}>
                  <View style={[
                    styles.toggleBadge,
                    currentSettings.counter_attack && styles.toggleBadgeActive,
                  ]}>
                    <Text style={[
                      styles.toggleText,
                      currentSettings.counter_attack && styles.toggleTextActive,
                    ]}>
                      {language === 'it' ? 'CONTROPIEDE' : 'COUNTER'}
                    </Text>
                    <Text style={[
                      styles.toggleValue,
                      currentSettings.counter_attack && styles.toggleValueActive,
                    ]}>
                      {currentSettings.counter_attack ? 'ON' : 'OFF'}
                    </Text>
                  </View>
                  <View style={[
                    styles.toggleBadge,
                    currentSettings.offside_trap && styles.toggleBadgeActive,
                  ]}>
                    <Text style={[
                      styles.toggleText,
                      currentSettings.offside_trap && styles.toggleTextActive,
                    ]}>
                      {language === 'it' ? 'FUORIGIOCO' : 'OFFSIDE'}
                    </Text>
                    <Text style={[
                      styles.toggleValue,
                      currentSettings.offside_trap && styles.toggleValueActive,
                    ]}>
                      {currentSettings.offside_trap ? 'ON' : 'OFF'}
                    </Text>
                  </View>
                </View>
              )}

              {/* Per-scenario Arrows */}
              {currentSettings?.arrows && Object.keys(currentSettings.arrows).length > 0 && (
                <View style={styles.arrowsScenSection}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'FRECCE' : 'ARROWS'}
                  </Text>
                  <View style={styles.arrowsGrid}>
                    {Object.entries(currentSettings.arrows).map(([pos, arrow]) => (
                      <View key={pos} style={styles.arrowItem}>
                        <Text style={styles.positionLabel}>{pos}</Text>
                        <Text style={[
                          styles.arrowIcon,
                          { color: arrow === '↓'
                              ? NothingTheme.colors.accent
                              : arrow === '↑'
                                ? '#FFFFFF'
                                : NothingTheme.colors.textTertiary },
                        ]}>
                          {arrow}
                        </Text>
                      </View>
                    ))}
                  </View>
                </View>
              )}

              {/* Tip */}
              {currentSettings && (
                <View style={styles.tipSection}>
                  <Text style={styles.sectionLabel}>TIP</Text>
                  <View style={styles.tipBox}>
                    <Text style={styles.tipText}>
                      {language === 'it' ? currentSettings.tip_it : currentSettings.tip_en}
                    </Text>
                  </View>
                </View>
              )}

              {/* Matchup Matrix Reverse Lookup */}
              {(selectedFormation?.effective_against?.length || selectedFormation?.vulnerable_to?.length) ? (
                <View style={styles.tipSection}>
                  {selectedFormation?.effective_against && selectedFormation.effective_against.length > 0 && (
                    <View style={{marginBottom: 16}}>
                      <Text style={styles.sectionLabel}>
                        {language === 'it' ? `BATTE (${selectedFormation.effective_against.length})` : `BEATS (${selectedFormation.effective_against.length})`}
                      </Text>
                      <View style={{flexDirection: 'row', flexWrap: 'wrap', gap: 6}}>
                        {selectedFormation.effective_against.map((opp: string, i: number) => (
                          <View key={i} style={[styles.tipBox, {paddingHorizontal: 10, paddingVertical: 6, borderLeftColor: '#FFFFFF'}]}>
                            <Text style={[styles.tipText, {fontSize: 11}]}>{opp}</Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  )}
                  {selectedFormation?.vulnerable_to && selectedFormation.vulnerable_to.length > 0 && (
                    <View>
                      <Text style={styles.sectionLabel}>
                        {language === 'it' ? `VULNERABILE A (${selectedFormation.vulnerable_to.length})` : `WEAK TO (${selectedFormation.vulnerable_to.length})`}
                      </Text>
                      <View style={{flexDirection: 'row', flexWrap: 'wrap', gap: 6}}>
                        {selectedFormation.vulnerable_to.map((opp: string, i: number) => (
                          <View key={i} style={[styles.tipBox, {paddingHorizontal: 10, paddingVertical: 6}]}>
                            <Text style={[styles.tipText, {fontSize: 11}]}>{opp}</Text>
                          </View>
                        ))}
                      </View>
                    </View>
                  )}
                </View>
              ) : null}

              {/* Strengths & Weaknesses */}
              <View style={styles.prosConsSection}>
                <View style={styles.prosConColumn}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'PUNTI FORZA' : 'STRENGTHS'}
                  </Text>
                  {(language === 'it' 
                    ? selectedFormation?.strengths_it 
                    : selectedFormation?.strengths_en
                  )?.map((item, idx) => (
                    <View key={idx} style={styles.prosConItem}>
                      <View style={styles.prosIndicator} />
                      <Text style={styles.prosConText}>{item}</Text>
                    </View>
                  ))}
                </View>

                <View style={styles.prosConColumn}>
                  <Text style={styles.sectionLabel}>
                    {language === 'it' ? 'DEBOLEZZE' : 'WEAKNESSES'}
                  </Text>
                  {(language === 'it' 
                    ? selectedFormation?.weaknesses_it 
                    : selectedFormation?.weaknesses_en
                  )?.map((item, idx) => (
                    <View key={idx} style={styles.prosConItem}>
                      <View style={styles.consIndicator} />
                      <Text style={styles.prosConText}>{item}</Text>
                    </View>
                  ))}
                </View>
              </View>
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
    flexDirection: 'row',
    alignItems: 'flex-end',
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
  },
  headerCount: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 'auto',
    marginBottom: 4,
  },
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
    marginHorizontal: 24,
  },
  defFilter: {
    flexDirection: 'row',
    paddingHorizontal: 24,
    paddingVertical: 14,
    gap: 8,
  },
  defBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 5,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
  },
  defBtnActive: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderColor: NothingTheme.colors.accent,
  },
  defBtnText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1,
  },
  defBtnTextActive: {
    color: NothingTheme.colors.accent,
  },
  dividerModal: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: 24,
    paddingTop: 16,
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
  metaBadgeText: {
    color: NothingTheme.colors.accent,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  formationPositions: {
    color: NothingTheme.colors.textTertiary,
    fontSize: 11,
    letterSpacing: 0.5,
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
  modalTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 32,
    fontWeight: '700',
    letterSpacing: 1,
    marginBottom: 8,
  },
  tacticTypeBadge: {
    backgroundColor: NothingTheme.colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  tacticTypeText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 10,
    fontWeight: '600',
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
  descriptionSection: {
    marginBottom: 24,
  },
  descriptionText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
  },
  arrowsInfo: {
    marginBottom: 24,
  },
  arrowsBox: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
  },
  arrowsText: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
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
  arrowsScenSection: {
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
    marginBottom: 24,
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
  prosConsSection: {
    marginBottom: 40,
  },
  prosConColumn: {
    marginBottom: 20,
  },
  prosConItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 8,
    gap: 10,
  },
  prosIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.textPrimary,
    marginTop: 4,
  },
  consIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: NothingTheme.colors.accent,
    marginTop: 4,
  },
  prosConText: {
    color: NothingTheme.colors.textSecondary,
    fontSize: 13,
    flex: 1,
    lineHeight: 18,
  },
});
